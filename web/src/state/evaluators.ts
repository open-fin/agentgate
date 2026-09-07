import type { EvaluatorOption } from '../api/client'

export function includeEvaluatorPrerequisites(
  selectedIds: string[], evaluators: EvaluatorOption[],
): { ids: string[]; added: string[] } {
  const byId = new Map(evaluators.map(item => [item.id, item]))
  const selected = new Set(selectedIds)
  const added: string[] = []
  const pending = [...selectedIds]

  while (pending.length) {
    const evaluator = byId.get(pending.pop()!)
    for (const prerequisite of evaluator?.prerequisites ?? []) {
      if (selected.has(prerequisite.evaluator_id)) continue
      selected.add(prerequisite.evaluator_id)
      added.push(prerequisite.evaluator_id)
      pending.push(prerequisite.evaluator_id)
    }
  }

  return {
    ids: evaluators.filter(item => selected.has(item.id)).map(item => item.id),
    added,
  }
}
