import os
import yaml
from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "agent_configs.yaml")

def load_agent_configs():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def create_agents(configs):
    agents = {}
    for name, cfg in configs["agents"].items():
        agents[name] = AssistantAgent(
            name=name,
            llm_config={
                "model": cfg["model"],
                "temperature": cfg["temperature"],
                "max_tokens": cfg["max_tokens"]
            },
            system_message=cfg["role"]
        )
    return agents

def create_orchestrator():
    configs = load_agent_configs()
    agents = create_agents(configs)


    user_proxy = UserProxyAgent(
    name="user_proxy",
    human_input_mode="NEVER",
    code_execution_config={"use_docker": False},
    llm_config={
        "model": "gpt-4o",  # ← este campo es obligatorio
        "api_key": os.getenv("OPENAI_API_KEY")
    }
    )


    group = GroupChat(
        agents=[user_proxy] + list(agents.values()),
        messages=[]
    )
    manager = GroupChatManager(
        groupchat=group,
        llm_config={"model": "gpt-4o"}
    )

    return manager, agents, user_proxy
