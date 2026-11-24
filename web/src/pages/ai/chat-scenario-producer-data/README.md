# Current scenario-tool producer corpus

`current.json` contains the exact UTF-8 response bodies and SHA-256 metadata from:

    uv run --frozen python tests/chat/chat_scenario_capture.py --out <owned-scratch-directory>

The capture ran against the current public ASGI application with the controlled native provider. It performed no real-model, DUT, MCP, PostgreSQL, browser, or external-network operation. Host-specific source roots and temporary paths are intentionally omitted; the source file hashes and HTTP metadata remain in the bundle.

The Web tests load this committed bundle through `chat-scenario-producer-fixture.ts`. They must not read `.hermes`, a user home directory, or another checkout. Synthetic state derivatives used to exercise quarantine-only UI branches are labelled in the tests and are not represented as captured ASGI responses.
