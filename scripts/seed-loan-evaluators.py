"""Initialize local synthetic datasets and published evaluators without model calls."""

import json
import os

from agentgate.demo.evaluators import ensure_loan_evaluators
from agentgate.demo.history import ensure_demo_history
from agentgate.server.dependencies import build_dependencies
from agentgate.storage.configuration import SQLiteConfig, load_database_config

if __name__ == "__main__":
    config = load_database_config()
    if (
        not isinstance(config, SQLiteConfig)
        or os.getenv("AGENTGATE_AGENT_PLATFORM_MODE", "mock") != "mock"
    ):
        raise SystemExit(
            "Local demo initialization requires SQLite; in-bank databases are not seeded."
        )
    dependencies = build_dependencies()
    try:
        print(json.dumps(ensure_loan_evaluators(dependencies.evaluators), ensure_ascii=False))
        print(
            json.dumps(
                {
                    "historical_records_inserted": ensure_demo_history(
                        config.path,
                        external_mode=True,
                    )
                },
                ensure_ascii=False,
            )
        )
    finally:
        dependencies.close()
