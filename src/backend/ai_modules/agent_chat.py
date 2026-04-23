import json
from typing import TypedDict, List
from langgraph.graph import StateGraph, END
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import SystemMessage, HumanMessage
import sys
import os

# To import utils properly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import load_llm_settings

import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

class AgentState(TypedDict):
    user_input: str
    parts_list: list
    parts3d: list
    agent_logs: List[str]
    is_approved: bool
    iterations: int

# Default values
model_name = "gemini-3.1-pro-preview"
temperature = 0.2
top_p = 0.8
max_tokens = 65535

try:
    llm_settings = load_llm_settings()
    func_settings = llm_settings.get("func_settings", {}).get("agent_chat", {})
    if func_settings:
        model_name = func_settings.get("model", model_name)
        temperature = func_settings.get("temperature", temperature)
        top_p = func_settings.get("top_p", top_p)
        max_tokens = func_settings.get("max_output_tokens", max_tokens)
    logging.info(f"Loaded agent_chat settings: model={model_name}, temp={temperature}")
except Exception as e:
    logging.warning(f"Failed to load llm_settings for agent_chat, using defaults: {e}")

# Initialize Vertex AI Chat Model
llm = ChatVertexAI(
    model_name=model_name,
    temperature=temperature,
    top_p=top_p,
    max_output_tokens=max_tokens,
    project="plan-craft",
    location="global"
)

def designer_node(state: AgentState):
    sys_prompt = """あなたはDIY家具の設計エージェントです。
ユーザーからの要望と、現在の部品リスト(parts_list)および3D情報(parts3d)を元に、新しい設計データをJSON形式で出力してください。
Reviewerからのフィードバックがある場合は、それに従って修正してください。
出力は必ずJSON形式で、以下のフォーマットのみを含めてください。
{
  "thought": "修正の意図や思考プロセス。UIに表示されるためユーザーに伝わる言葉で。",
  "parts_list": [...],
  "parts3d": [...]
}
"""
    context = f"ユーザーの要望: {state['user_input']}\n\n現在の部品リスト:\n{json.dumps(state['parts_list'], ensure_ascii=False)}\n\n現在の3D情報:\n{json.dumps(state['parts3d'], ensure_ascii=False)}"
    if state["agent_logs"]:
        context += f"\n\nこれまでのやり取り:\n" + "\n".join(state["agent_logs"])
    
    msg = llm.invoke([
        SystemMessage(content=sys_prompt),
        HumanMessage(content=context)
    ])
    
    try:
        content = msg.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        data = json.loads(content)
        thought = data.get("thought", "設計を更新しました。")
        new_parts_list = data.get("parts_list", state["parts_list"])
        new_parts3d = data.get("parts3d", state["parts3d"])
        
        logs = state["agent_logs"] + [f"[Designer] {thought}"]
        return {
            "parts_list": new_parts_list,
            "parts3d": new_parts3d,
            "agent_logs": logs,
            "iterations": state["iterations"] + 1
        }
    except Exception as e:
        logs = state["agent_logs"] + [f"[Designer] エラーが発生しました: {e}"]
        return {"agent_logs": logs, "iterations": state["iterations"] + 1}

def reviewer_node(state: AgentState):
    sys_prompt = """あなたは構造評価エージェントです。
提案された部品リストと3D情報を見て、物理的・構造的な破綻（脚の長さが揃っていない、接合部が浮いている、不安定等）がないかチェックしてください。
出力は以下のJSON形式のみを含めてください。
{
  "thought": "評価の理由と思考プロセス。UIに表示されるためユーザーに伝わる言葉で。",
  "is_approved": true または false
}
"""
    context = f"提案された部品リスト:\n{json.dumps(state['parts_list'], ensure_ascii=False)}\n\n提案された3D情報:\n{json.dumps(state['parts3d'], ensure_ascii=False)}"
    
    msg = llm.invoke([
        SystemMessage(content=sys_prompt),
        HumanMessage(content=context)
    ])
    
    try:
        content = msg.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        data = json.loads(content)
        thought = data.get("thought", "評価を完了しました。")
        is_approved = data.get("is_approved", False)
        
        logs = state["agent_logs"] + [f"[Reviewer] {thought}"]
        return {
            "is_approved": is_approved,
            "agent_logs": logs
        }
    except Exception as e:
        logs = state["agent_logs"] + [f"[Reviewer] エラーが発生しました: {e}"]
        return {"agent_logs": logs, "is_approved": False}

def router(state: AgentState):
    if state["is_approved"] or state["iterations"] >= 3:
        return END
    return "designer"

workflow = StateGraph(AgentState)
workflow.add_node("designer", designer_node)
workflow.add_node("reviewer", reviewer_node)
workflow.set_entry_point("designer")
workflow.add_edge("designer", "reviewer")
workflow.add_conditional_edges("reviewer", router)
agent_app = workflow.compile()

def run_chat_workflow(user_input: str, parts_list: list, parts3d: list):
    initial_state = AgentState(
        user_input=user_input,
        parts_list=parts_list,
        parts3d=parts3d,
        agent_logs=[],
        is_approved=False,
        iterations=0
    )
    result = agent_app.invoke(initial_state)
    return {
        "parts_list": result["parts_list"],
        "parts3d": result["parts3d"],
        "agent_logs": result["agent_logs"]
    }
