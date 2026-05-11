import time
from autogen import ConversableAgent
from gpt4all import GPT4All

class GPT4AllAgent(ConversableAgent):
    def __init__(self, name, model_path, model_name, system_message=None):
        super().__init__(name=name, system_message=system_message)
        self.model = GPT4All(model_name=model_name, model_path=model_path, allow_download=False)

    def generate_reply(self, message, **kwargs):
        max_tokens = kwargs.get("max_tokens", 512)
        print(f"🕒 Generando respuesta para: '{message}'...")
        start_time = time.time()
        response = self.model.generate(message, max_tokens=max_tokens)
        end_time = time.time()
        print(f"✅ Respuesta generada en {end_time - start_time:.2f} segundos.")
        return response

# Instanciar el agente
agent = GPT4AllAgent(
    name="TestAgent",
    model_path="models/",
    model_name="mistral-7b-instruct-v0.1.Q4_0",
    system_message="Sos un agente financiero que responde con claridad y precisión."
)

# Enviar mensaje de prueba
response = agent.generate_reply("¿Qué factores afectan el precio de las acciones?")
print("🧠 Respuesta del agente:")
print(response)
