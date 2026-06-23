"""LangGraph Studio entry point.

Builds the graph inline with checkpointer=False so LangGraph Studio can
inject its own persistence layer. Not used by the FastAPI app.
"""
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition

from backend.agent.graph import _make_tools, _store, build_system_prompt
from backend.config import settings
from backend.rag.pipeline.graph import RagPipelineGraph
from backend.schemas import UserProfile

_profile = UserProfile(
    username="studio_user",
    skin_type="normal",
    skin_concerns=["acne", "dark spots"],
    has_shaving_routine=True,
    medical_flags=[],
    onboarding_complete=True,
)

_tools = _make_tools("studio_user", _store)
_system_prompt = build_system_prompt(_profile, _store)

_llm = ChatOpenAI(
    model=settings.llm_model,
    openai_api_key=settings.openrouter_api_key,
    openai_api_base=settings.openrouter_base_url,
    temperature=0.3,
).bind_tools(_tools)


def _agent(state: MessagesState):
    messages = [SystemMessage(content=_system_prompt)] + state["messages"]
    return {"messages": [_llm.invoke(messages)]}


_builder = StateGraph(MessagesState)
_builder.add_node("agent", _agent)
_builder.add_node("tools", ToolNode(_tools))
_builder.set_entry_point("agent")
_builder.add_conditional_edges("agent", tools_condition)
_builder.add_edge("tools", "agent")

graph = _builder.compile(checkpointer=False)

rag_graph = RagPipelineGraph()._graph
