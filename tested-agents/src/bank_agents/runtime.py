"""Three genuinely different execution paths sharing tools, not canned answers."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, ConfigDict, Field

from .telemetry import Evidence, PROJECT
from .tools import LoanTools, TOOLS, decision


from .versions import (BASE_PROMPT, EXTRACT_PROMPT, ROUTER_PROMPT, SUMMARY_PROMPT, SKILLS,
                       loan_version, session_scope, summary_prompt)


class Extracted(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    amount: float | None = Field(default=None, gt=0, le=10000000, allow_inf_nan=False)
    purpose: str | None = Field(default=None, min_length=1, max_length=200)
    intent: str


def build_loan_workflow(handlers: Mapping[str, Callable[[dict], dict]], version="v1"):
    """One graph definition for execution and descriptor export."""
    graph = StateGraph(dict)
    definitions = (
        ("extract", "信息提取", "llm", "根据对话提取意图、金额和用途，检查缺失资料"),
        ("submit", "提交申请", "tool", "调用 submit_application 创建测试申请"),
        ("credit", "征信查询", "tool", "调用 credit_inquiry 查询测试客户风险"),
        ("decide", "规则决策", "rule", "按测试政策确定通过、转人工或拒绝"),
        ("act", "执行动作", "tool", "依据决策调用 approve_loan、request_human_review 或 reject_loan"),
        ("lookup", "查询申请", "tool", "调用 get_application 查询本会话申请"),
        ("end", "生成回复", "llm", "依据实际状态回复，或追问缺失资料；声明测试环境"),
    )
    if set(handlers) != {row[0] for row in definitions}:
        raise ValueError("workflow handlers must match declared nodes")
    for node_id, label, node_type, description in definitions:
        graph.add_node(node_id, handlers[node_id], metadata={
            "label": label, "node_type": node_type, "description": description,
            "trace_name": f"workflow.{node_id}",
        })

    def route(state):
        if state["intent"] == "status" and version != "evolution-v1":
            return "查询进度"
        if state["intent"] in ({"apply", "status"} if version == "evolution-v1" else {"apply"}) and not state["missing"]:
            return "申请且资料齐全"
        return "缺资料或咨询"

    graph.add_edge(START, "extract")
    graph.add_conditional_edges("extract", route, {
        **({"查询进度": "lookup"} if version != "evolution-v1" else {}),
        "申请且资料齐全": "submit", "缺资料或咨询": "end",
    })
    for before, after in (("submit", "credit"), ("credit", "decide"),
                          ("decide", "act"), ("act", "end"), ("lookup", "end")):
        graph.add_edge(before, after)
    graph.add_edge("end", END)
    return graph


def loan_workflow_topology(version="v1") -> dict:
    """Export the execution graph without executing model, tools or storage."""
    def not_executable(_):
        raise RuntimeError("descriptor-only workflow cannot execute")

    graph = build_loan_workflow(dict.fromkeys(
        ("extract", "submit", "credit", "decide", "act", "lookup", "end"),
        not_executable,
    ), version)
    nodes = []
    for node_id in (START, *graph.nodes, END):
        metadata = graph.nodes[node_id].metadata if node_id in graph.nodes else {}
        terminal = node_id in {START, END}
        nodes.append({
            "id": node_id, "kind": "workflow",
            "label": ("开始" if node_id == START else "结束") if terminal else metadata["label"],
            "description": "流程入口" if node_id == START else "流程结束" if node_id == END else metadata["description"],
            "node_type": "terminal" if terminal else metadata["node_type"],
            "trace_name": None if terminal else metadata["trace_name"],
        })
    edges = [{"source": source, "target": target, "relation": "下一步"}
             for source, target in sorted(graph.edges)]
    for source, branches in graph.branches.items():
        for branch in branches.values():
            edges.extend({"source": source, "target": target, "relation": label}
                         for label, target in branch.ends.items())
    return {"composition": "工作流 · 条件分支", "nodes": nodes, "edges": edges}


class Runtime:
    def __init__(self, store, model, trace_directory: Path):
        self.store, self.model, self.trace_directory = store, model, trace_directory

    def execute(self, mode, session_id, request_id, text, version="v1"):
        loan_version(version)
        session = self.store.session(session_id, session_scope(mode, version))
        payload = {"text": text, "mode": mode}
        if version != "v1":
            payload["version"] = version
        cached = self.store.reserve(request_id, session_id, payload)
        if cached is not None:
            return cached
        row = self.store.request(request_id)
        evidence = None
        try:
            evidence = Evidence(self.trace_directory, row["trace_id"], session_id, mode, text, version)
            tools = LoanTools(self.store, session_id, request_id, evidence)
            messages = [*session["data"]["messages"], {"role": "user", "content": text}]
            progress = []
            slots = {} if version == "evolution-v1" else dict(session["data"]["slots"])
            if version == "evolution-v1":
                messages = messages[-1:]
            with evidence.span(f"agent.{mode}", "agent", inputs={"txt": text}) as root:
                if mode == "base":
                    answer = self._base(messages, tools, evidence, version)
                    skill = "base_tools"
                elif mode == "workflow":
                    answer = self._workflow(messages, slots, tools, evidence, progress, version)
                    skill = "loan_workflow"
                elif mode == "cloudshrimp":
                    answer, skill = self._cloud(messages, slots, tools, evidence, progress, version, session["data"].get("skill"))
                else:
                    raise ValueError("unknown execution mode")
                state = self.store.application(session_id)
                result = {"status": "completed", "output": answer, "intent_code": skill,
                          "session_id": session_id, "request_id": request_id, "turn_id": request_id,
                          "project_id": PROJECT, "trace_id": row["trace_id"], "agent_version": version,
                          "mode": mode, "slots": slots, "final_state": state, "test_only": True,
                          "workflow_calls": progress}
                root["output"] = result
            evidence.finish(result)
            messages.append({"role": "assistant", "content": answer})
            self.store.finish(request_id, result, {"messages": messages[-40:], "slots": slots, "skill": skill})
            return result
        except Exception as exc:
            try:
                if evidence is not None and evidence.collector.active_trace_id:
                    evidence.finish({"error": type(exc).__name__}, failed=True)
            finally:
                self.store.finish(request_id, {"error": type(exc).__name__, "trace_id": row["trace_id"]}, failed=True)
            raise

    def _base(self, history, tools, evidence, version="v1"):
        messages = [{"role": "system", "content": BASE_PROMPT}, *history]
        for _ in range(10):
            response = self.model.complete(messages, evidence, tools=TOOLS)
            messages.append(response)
            calls = response.get("tool_calls") or []
            if not calls:
                answer = response.get("content")
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("empty final answer")
                return answer
            if len(calls) > 8:
                raise ValueError("too many tool calls")
            for call in calls:
                function = call["function"]
                arguments = json.loads(function["arguments"])
                result = tools.invoke(function["name"], arguments)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)})
                if version == "evolution-v1" and "error" in result:
                    return self._summary(history, tools, evidence, version=version)
        raise ValueError("model tool loop exceeded 10 iterations")

    def _summary(self, history, tools, evidence, missing=None, version="v1"):
        state = self.store.application(tools.session)
        message = self.model.complete([{"role": "system", "content": summary_prompt(version)}, *history,
            {"role": "user", "content": "可信测试数据库状态与缺失字段：" + json.dumps({"state": state, "missing": missing or []}, ensure_ascii=False)}], evidence)
        answer = message.get("content")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("summary returned no text")
        return answer

    def _workflow(self, history, slots, tools, evidence, progress, version="v1"):
        def node(name, fn):
            def execute(state):
                with evidence.span(f"workflow.{name}", inputs=state) as span:
                    update = fn(state)
                    span["output"] = update
                    progress.append({"node_id": name, "node_output": update})
                    return update
            return execute

        def extract(_):
            parsed = Extracted.model_validate(self.model.structured(EXTRACT_PROMPT, history, evidence))
            if parsed.intent not in {"apply", "status", "help"}:
                raise ValueError("invalid workflow intent")
            for key in ("amount", "purpose"):
                if getattr(parsed, key) is not None:
                    slots[key] = getattr(parsed, key)
            return {"intent": parsed.intent, "missing": [key for key in ("amount", "purpose") if not slots.get(key)]}

        def submit(_):
            value = tools.invoke("submit_application", slots)
            if "error" in value:
                raise ValueError("application submission rejected")
            return {"application": value}

        def credit(_):
            value = tools.invoke("credit_inquiry", {})
            if "error" in value:
                raise ValueError("credit inquiry rejected")
            return {"credit": value}

        def decide(state):
            value = decision(state["application"], state["credit"])
            if version == "evolution-v1" and value == "approved" and state["application"]["amount"] >= 200000:
                value = "pending_review"
            return {"decision": value}

        def act(state):
            name = {"approved": "approve_loan", "pending_review": "request_human_review", "rejected": "reject_loan"}[state["decision"]]
            value = tools.invoke(name, {})
            if "error" in value and version != "evolution-v1":
                raise ValueError("decision rejected")
            return {"application": value}

        # dict state nodes return complete accumulated state; no hidden checkpoint state.
        def wrap(name, fn):
            run = node(name, fn)
            return lambda state: {**state, **run(state)}

        graph = build_loan_workflow({
            "extract": wrap("extract", extract),
            "submit": wrap("submit", submit),
            "credit": wrap("credit", credit),
            "decide": wrap("decide", decide),
            "act": wrap("act", act),
            "lookup": wrap("lookup", lambda _: {"application": tools.invoke("get_application", {})}),
            "end": wrap("end", lambda state: {"output": self._summary(history, tools, evidence, state.get("missing"), version)}),
        }, version)
        return graph.compile().invoke({})["output"]

    def _cloud(self, history, slots, tools, evidence, progress, version="v1", previous_skill=None):
        def route(_):
            with evidence.span("skill.route", inputs=history) as span:
                selected = ({"skill": previous_skill} if version == "evolution-v1" and previous_skill
                            else self.model.structured(ROUTER_PROMPT, history, evidence))
                if set(selected) != {"skill"} or selected["skill"] not in {s["id"] for s in SKILLS}:
                    raise ValueError("unknown Skill selected")
                span["output"] = {"selected_skill": selected["skill"]}
                return selected

        def invoke(state):
            skill = state["skill"]
            with evidence.span(f"skill.{skill}", inputs={"slots": slots}, metadata={"skill_id": skill, "version": version}) as span:
                scoped_tools = tools
                if version == "evolution-v2":
                    allowed = next(s["tools"] for s in SKILLS if s["id"] == skill)
                    scoped_tools = LoanTools(self.store, tools.session, tools.request, evidence, allowed_tools=frozenset(allowed))
                if skill == "loan_application":
                    answer = self._workflow(history, slots, scoped_tools, evidence, progress, version)
                else:
                    if skill == "application_status":
                        scoped_tools.invoke("get_application", {})
                    answer = self._summary(history, scoped_tools, evidence, version=version)
                span["output"] = {"output": answer}
                return {**state, "output": answer}
        graph = StateGraph(dict)
        graph.add_node("route", route)
        for skill in SKILLS:
            graph.add_node(skill["id"], invoke)
            graph.add_edge(skill["id"], END)
        graph.add_edge(START, "route")
        graph.add_conditional_edges("route", lambda state: state["skill"])
        result = graph.compile().invoke({})
        return result["output"], result["skill"]
