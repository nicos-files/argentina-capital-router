from autogen import ConversableAgent
from gpt4all import GPT4All
import time

class GPT4AllAgent(ConversableAgent):
    def __init__(self, name, model_path, model_name, system_message=None):
        super().__init__(name=name, system_message=system_message)
        self.model = GPT4All(model_name=model_name, model_path=model_path, allow_download=False)

    def generate_reply(self, message, **kwargs):
        print(f"🧠 [{self.name}] Recibió mensaje: {message}")
        max_tokens = kwargs.get("max_tokens", 128)
        print(f"🕒 [{self.name}] Generando respuesta...")
        start = time.time()
        response = self.model.generate(message, max_tokens=max_tokens)
        print(f"✅ [{self.name}] Respuesta generada en {time.time() - start:.2f} segundos.")
        return response
