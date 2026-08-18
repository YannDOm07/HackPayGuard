"""PayGuard agent — Claude on Amazon Bedrock, driving the payment engine.

Design principle: the LLM is stateless and amnesiac BY DESIGN. All memory
lives in CockroachDB:
  - every factual answer comes from a tool call (SQL / vector search),
  - every user/assistant turn is persisted in `conversations`,
  - on boot, the agent's first action is the recovery routine.

We use the official Anthropic SDK's Bedrock client and a transparent manual
tool-use loop (easy to demo and to reason about).
"""
import uuid

from anthropic import AnthropicBedrock

from . import config, engine, tools
from .db import get_conn

SYSTEM_PROMPT = """You are PayGuard, an autonomous CFO agent for a small business.
You verify invoices, detect fraud, and execute supplier payments with one absolute
guarantee: no payment is ever lost, and no supplier is ever paid twice.

Rules you live by:
- Your ONLY memory is the CockroachDB database, accessed through your tools.
  Never invent payment data: if the user asks about invoices, payments or history,
  call a tool. If a tool returns nothing, say so honestly.
- Every payment goes through the idempotent state machine
  (INTENT -> VALIDATED -> EXECUTING -> EXECUTED -> CONFIRMED). You never bypass it.
- If a payment comes back BLOCKED, explain the fraud evidence to the user, cite the
  supplier's payment history, and ask for explicit human confirmation. NEVER retry
  a BLOCKED payment on your own.
- For audit questions ("payments above X in March"), write a precise SQL SELECT
  with audit_query and present the results clearly.
- Amounts are in XOF (FCFA) unless stated otherwise. Answer in the user's language
  (French or English). Be concise and precise — you are handling money.
"""


class PayGuardAgent:
    def __init__(self, session_id: str | None = None):
        self.client = AnthropicBedrock(aws_region=config.AWS_REGION)
        self.model = config.BEDROCK_MODEL_ID
        self.session_id = session_id or f"session-{uuid.uuid4().hex[:8]}"
        self.messages: list[dict] = []  # context window only — NOT the memory

    def startup(self, conn) -> None:
        """First action on every boot: 'where was I?'"""
        engine.recover(conn)

    def _persist(self, conn, role: str, content: str) -> None:
        conn.execute(
            "INSERT INTO conversations (session_id, role, content) VALUES (%s, %s, %s)",
            (self.session_id, role, content),
        )
        conn.commit()

    def chat(self, conn, user_message: str, on_tool=None) -> str:
        """One user turn. Runs the tool loop until Claude produces a final answer."""
        self._persist(conn, "user", user_message)
        self.messages.append({"role": "user", "content": user_message})

        while True:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=tools.TOOL_DEFS,
                messages=self.messages,
            )
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                text = "".join(b.text for b in response.content if b.type == "text")
                self._persist(conn, "assistant", text)
                return text

            results = []
            for block in response.content:
                if block.type == "tool_use":
                    if on_tool:
                        on_tool(block.name, block.input)
                    output = tools.run_tool(conn, block.name, dict(block.input))
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    })
            self.messages.append({"role": "user", "content": results})


def run_chat_cli() -> None:
    """Interactive terminal chat (used for the demo + amnesia test)."""
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    agent = PayGuardAgent()
    with get_conn() as conn:
        console.print(Panel.fit(
            f"[bold cyan]PayGuard[/] — session [yellow]{agent.session_id}[/]\n"
            "Fresh LLM context. All memory lives in CockroachDB.\n"
            "Type 'exit' to quit.",
            title="PayGuard agent"))
        console.print("[dim]-> startup recovery: asking the database 'where was I?'[/]")
        agent.startup(conn)

        while True:
            try:
                user = console.input("\n[bold green]you>[/] ")
            except (EOFError, KeyboardInterrupt):
                break
            if user.strip().lower() in ("exit", "quit"):
                break
            if not user.strip():
                continue
            reply = agent.chat(
                conn, user,
                on_tool=lambda n, a: console.print(f"[dim]  tool: {n}({a})[/]"),
            )
            console.print(Panel(reply, title="PayGuard", border_style="cyan"))
