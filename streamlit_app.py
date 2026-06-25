"""Interactive demo UI for the listicle pipeline.

Same two gates as the CLI (`pipeline/run.py`), same pipeline functions —
this just renders them as a browser flow instead of terminal output:

  Gate 1: run research -> review the tool table -> approve
  Gate 2: generate + assemble + QA -> review checks/draft -> publish

Mock mode (default) is free and offline. Live mode needs a visitor-supplied
Anthropic API key, used only in-memory for that session — never stored or
committed.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st
import yaml

from pipeline import assemble, generate, qa, research
from pipeline.llm import LiveAnthropicClient, MockClient

ROOT = Path(__file__).resolve().parent
CATEGORIES_DIR = ROOT / "config" / "categories"
FIXTURES_DIR = ROOT / "fixtures" / "event_registration_software"


def _load_yaml(p) -> dict:
    return yaml.safe_load(Path(p).read_text())


def _qa_report_md(report, sections, editorial=None) -> str:
    lines = [f"# QA report — {sections.title}", "",
             f"- words: {report.word_count}  ·  read time: ~{report.read_minutes} min",
             f"- hard fail: {report.hard_fail}", "", "| check | status | detail |",
             "| --- | --- | --- |"]
    for c in report.checks:
        lines.append(f"| {c.name} | {c.status.upper()} | {c.detail} |")
    if editorial:
        lines += ["", f"## Editorial review — {editorial['score']}/100",
                  f"_{editorial['verdict']}_", ""]
        lines += [f"- {i}" for i in editorial.get("issues", [])] or ["- (no issues flagged)"]
    return "\n".join(lines) + "\n"


house_style = _load_yaml(ROOT / "config" / "house_style.yaml")

st.set_page_config(page_title="Listicle Pipeline", layout="wide")
st.title("Listicle Generation Pipeline")
st.caption(
    "Research → **Gate 1** (verify facts) → Generate → Assemble → QA → "
    "**Gate 2** (editorial sign-off). Same pipeline as the CLI — see ARCHITECTURE.md."
)

if "bundle" not in st.session_state:
    st.session_state.bundle = None
if "draft" not in st.session_state:
    st.session_state.draft = None

with st.sidebar:
    st.header("Configuration")
    category_files = sorted(CATEGORIES_DIR.glob("*.yaml"))
    chosen_file = st.selectbox(
        "Category", category_files, format_func=lambda p: p.stem.replace("_", " ")
    )
    mode_choice = st.radio("Mode", ["Mock (offline, free)", "Live (real web search)"])
    is_mock = mode_choice.startswith("Mock")
    model, api_key = "claude-sonnet-4-6", None
    if not is_mock:
        model = st.selectbox("Model", ["claude-sonnet-4-6", "claude-opus-4-8"])
        api_key = st.text_input("Your Anthropic API key", type="password")
        st.caption("Used only for this session, never stored. Web search must be "
                   "enabled for this key in the Claude Console.")
    run_research = st.button("1. Run research", use_container_width=True, type="primary")


def _client():
    if is_mock:
        return MockClient(FIXTURES_DIR)
    if not api_key:
        st.error("Enter an API key in the sidebar, or switch to Mock mode.")
        st.stop()
    return LiveAnthropicClient(model=model, house_style=house_style, api_key=api_key)


if run_research:
    inp = _load_yaml(chosen_file)
    with st.spinner(f"Researching {inp['tool_count']} {inp['category_label']}..."):
        try:
            bundle = research.run(
                _client(), inp, house_style, "mock" if is_mock else "live",
                "" if is_mock else model,
            )
        except Exception as e:
            st.error(f"Research failed: {e}")
            st.stop()
    st.session_state.bundle = bundle
    st.session_state.draft = None

bundle = st.session_state.bundle
if bundle:
    st.subheader("Gate 1 — verify research")
    st.dataframe(
        [{
            "Tool": t.name + (" ★ house" if t.is_house else ""),
            "Pricing": t.pricing,
            "G2": t.g2_rating or "—",
            "Capterra": t.capterra_rating or "—",
            "Sources": len(t.sources),
        } for t in bundle.tools],
        use_container_width=True, hide_index=True,
    )
    col1, col2 = st.columns([1, 3])
    col1.download_button("Download research.json", bundle.model_dump_json(indent=2),
                          file_name="research.json", mime="application/json")
    if col2.button("2. Approve research → generate draft", type="primary"):
        with st.spinner("Generating sections, assembling, running QA..."):
            try:
                sections = generate.run(_client(), bundle, house_style)
                md = assemble.run(bundle, sections, house_style)
                report = qa.run(md, bundle, sections, house_style)
                editorial = _client().score_editorial(md, bundle)
            except Exception as e:
                st.error(f"Generate failed: {e}")
                st.stop()
        st.session_state.draft = {
            "md": md, "report": report, "sections": sections, "editorial": editorial,
        }

draft = st.session_state.draft
if draft:
    report, sections, editorial = draft["report"], draft["sections"], draft["editorial"]
    st.subheader("Gate 2 — editorial sign-off")
    st.write(
        f"**{report.word_count} words** · ~{report.read_minutes} min read · "
        + ("\U0001f534 hard checks FAILED" if report.hard_fail else "\U0001f7e2 all hard checks pass")
    )
    st.dataframe(
        [{"Check": c.name, "Status": c.status.upper(), "Detail": c.detail} for c in report.checks],
        use_container_width=True, hide_index=True,
    )
    if editorial:
        st.write(f"**Editorial score: {editorial['score']}/100** — {editorial['verdict']}")
        for issue in editorial.get("issues", []):
            st.write(f"- {issue}")

    qa_md = _qa_report_md(report, sections, editorial)

    c1, c2 = st.columns(2)
    c1.download_button("Download draft.md", draft["md"], file_name="draft.md")
    c2.download_button("Download qa_report.md", qa_md, file_name="qa_report.md")

    st.markdown("---")
    st.markdown(draft["md"])
