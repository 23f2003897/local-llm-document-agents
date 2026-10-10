"""Excel Q&A agent: a local LLM that writes and runs pandas code, searches the web, and answers in plain English.

The model is given two tools:
  - run_python(code): executes Python with the inventory sheet preloaded as `df`
  - web_search(query): DuckDuckGo search for definitions / context
It loops (call tools -> read results -> call more tools) until it produces a final answer.
"""
import ast
import contextlib
import io
import json
import re
from pathlib import Path

import ollama
import pandas as pd

MODEL = "qwen3:8b"
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "q1" / "Inventory-Records-Sample-Data.xlsx"
MAX_STEPS = 8
HISTORY_TURNS = 2  # previous user/assistant exchanges sent with each question
LONG_OUTPUT_LINES = 25  # code outputs longer than this get a "filter in code instead" note
NUM_CTX = 12288  # Ollama defaults to 4096 tokens, too small for tool outputs + chat history


def load_inventory(path=DATA_PATH):
    """The sheet has a title block above the table; find the header row ('Product ID') and clean column names."""
    raw = pd.read_excel(path, header=None)
    header_row = raw.index[raw.apply(lambda r: r.astype(str).str.strip().eq("Product ID").any(), axis=1)][0]
    df = pd.read_excel(path, header=header_row)
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
    df.columns = [re.sub(r"\s+", " ", str(c)).replace("- ", "-").replace("/ ", "/").strip() for c in df.columns]
    return df.dropna(how="all").reset_index(drop=True)


DF = load_inventory()


# ---------------- tools ----------------

def run_python(code: str) -> str:
    """Run Python code against the inventory DataFrame `df` (pandas is `pd`). Print what you need to see."""
    buf = io.StringIO()
    scope = {"df": DF.copy(), "pd": pd}
    # Print whole tables: pandas' default "..." truncation hides columns, and the model then guesses the values.
    wide = pd.option_context("display.max_columns", None, "display.width", 250, "display.max_rows", 200)
    try:
        with contextlib.redirect_stdout(buf), wide:
            tree = ast.parse(code)
            # If the last statement is an expression, show its value like a notebook would
            # (works for "a = 1; df.head()" on one line too).
            last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
            exec(compile(tree, "<code>", "exec"), scope)
            if last is not None:
                value = eval(compile(ast.Expression(last.value), "<code>", "eval"), scope)
                if value is not None:
                    print(value)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"
    out = buf.getvalue().strip()
    if not out:
        return "(The code ran but printed nothing, so there is no result yet. Add print(...) to see values.)"
    return (out[:4000] + "\n...[truncated]") if len(out) > 4000 else out


def web_search(query: str) -> str:
    """Search the web for a definition or background context. Returns the top results as text."""
    try:
        from ddgs import DDGS
        hits = DDGS().text(query, max_results=4)
    except Exception as e:  # network down, rate-limited, etc.
        return f"Search failed: {e}"
    if not hits:
        return "No results."
    return "\n\n".join(f"{h.get('title')}\n{h.get('body')}\nSource: {h.get('href')}" for h in hits)


TOOLS = {"run_python": run_python, "web_search": web_search}

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "run_python",
        "description": "Execute Python code against the inventory data. A pandas DataFrame `df` is preloaded "
                       "(pandas imported as `pd`). Print results you need.",
        "parameters": {"type": "object", "properties": {"code": {"type": "string", "description": "Python code"}},
                       "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web to look up the definition or business meaning of a term "
                       "(e.g. 'hand-in-stock', 'inventory turnover').",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]


def _schema():
    buf = io.StringIO()
    DF.info(buf=buf)
    return f"{buf.getvalue()}\nFirst rows:\n{DF.head(3).to_string()}"


SYSTEM_PROMPT = f"""You are a data analyst assistant for an inventory spreadsheet.

The data is loaded as a pandas DataFrame `df`:
{_schema()}

Rules:
1. For EVERY question about numbers, products or totals, call run_python and compute the answer from `df` -
   even if a similar question was answered earlier. Never guess or do mental arithmetic on the data.
2. Only state numbers and product IDs that appear in the tool output. Whenever you print products, include
   the 'Product ID' and 'Product Name' columns along with the values (the row index is NOT the product ID).
3. Do the filtering, counting and comparing IN CODE and print only the rows/values that answer the question
   (e.g. `df[cond][cols]`, `len(...)`). Never print a whole table and pick values out of it by eye.
   If run_python returns an ERROR, fix the code and call run_python again - never answer with the error.
4. If the user asks what a term means, or a column name is ambiguous, call web_search to look up the definition,
   then relate it to this dataset.
5. Final answer: a short plain-English summary (2-5 sentences) with the key numbers, exactly as computed
   (keep 2 decimal places for non-whole numbers; never round them away). Mention which product IDs
   are involved where relevant. Do not show code in the final answer.
6. For highest/lowest/top-N questions, check for ties (e.g. `df[df[col] == df[col].max()]`) and mention them.
7. If the data cannot answer the question, say so plainly.
"""


def chat(history, on_step=None):
    """Run one user turn. `history` is a list of {'role','content'} dicts (user/assistant only).

    Returns (answer, steps) where steps is a list of tool calls made, for display.
    """
    # Only recent turns are sent: an 8B model drifts (skips tools, misquotes numbers) as the chat grows long.
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(history)[-(HISTORY_TURNS * 2 + 1):]
    steps = []
    nudged = False
    for _ in range(MAX_STEPS):
        reply = ollama.chat(model=MODEL, messages=messages, tools=TOOL_SPECS, think=True,
                            options={"temperature": 0, "num_ctx": NUM_CTX})
        msg = reply["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            answer = msg.get("content", "").strip()
            ran_code = any(s["tool"] == "run_python" for s in steps)
            states_data = re.search(r"\bP1\d\d\b|\$\s?\d|\d+\s+units", answer)
            if not nudged and (not steps or (states_data and not ran_code)):
                # Answers must be grounded in tool output: bounce (once) an answer given with no tool call, or one
                # that quotes data values without having run any code this turn.
                nudged = True
                messages.append({"role": "assistant", "content": answer})
                messages.append({"role": "user", "content": "Your answer was not computed from the data in this turn. "
                                 "Call run_python to compute every value you state, then answer only from its output."})
                continue
            return answer, steps
        messages.append({"role": "assistant", "content": msg.get("content", ""),
                         "tool_calls": [{"function": {"name": c["function"]["name"],
                                                      "arguments": c["function"]["arguments"]}} for c in calls]})
        for c in calls:
            name = c["function"]["name"]
            args = c["function"]["arguments"]
            if isinstance(args, str):
                args = json.loads(args)
            fn = TOOLS.get(name)
            result = fn(**args) if fn else f"Unknown tool {name}"
            step = {"tool": name, "input": args, "output": result}
            steps.append(step)
            if on_step:
                on_step(step)
            if name == "run_python" and result.count("\n") >= LONG_OUTPUT_LINES:
                # Reading answers off a long printout is where the model makes mistakes; push it to filter in code.
                result += (f"\n\n[Note: this output has {result.count(chr(10)) + 1} lines. Do not read the answer off it - "
                           "run code that filters/aggregates so it prints only the rows or values that answer "
                           "the question.]")
            messages.append({"role": "tool", "content": result, "tool_name": name})
    # Step limit reached: ask for a final answer from the tool outputs gathered so far instead of giving up.
    messages.append({"role": "user", "content": "Stop calling tools. Answer the question now using only the tool "
                     "outputs above; say clearly if something could not be computed."})
    reply = ollama.chat(model=MODEL, messages=messages, think=True, options={"temperature": 0, "num_ctx": NUM_CTX})
    return reply["message"].get("content", "").strip(), steps


if __name__ == "__main__":
    history = []
    print("Inventory agent. Type 'quit' to exit.")
    while True:
        q = input("\nYou: ").strip()
        if q.lower() in {"quit", "exit"}:
            break
        history.append({"role": "user", "content": q})
        answer, steps = chat(history, on_step=lambda s: print(f"  [{s['tool']}] {json.dumps(s['input'])[:200]}"))
        history.append({"role": "assistant", "content": answer})
        print(f"\nAgent: {answer}")
