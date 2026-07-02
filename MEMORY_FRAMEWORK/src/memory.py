from typing import List, Dict, TypedDict, Union
from datetime import datetime


class Memory:


    def __init__(self, system_prompt):
        self.system_prompt = system_prompt
        self.memory = [
            {
                "role": "system",
                "content": system_prompt
            }
        ]


    def add_session_messages(self,message:Union[List[dict],dict]):
        if isinstance(message,dict):
            self.memory.append(message)
        elif isinstance(message,List[dict]):
            self.memory.extend(message)
        else:
            raise ValueError


    def get_session_messages(self, num_convo=None):
        if not num_convo:
            return self.memory
        else:
            return self.memory[:1] + self.memory[-num_convo:]


    def clear_session(self):
        self.memory = [{
            "role": "system",
            "content": self.system_prompt
        }]


class SessionManager:

    def __init__(self):
        self.memories = {}  


    def is_session_present(self, session_id):
        return session_id in self.memories


    def create_memory(self, session_id, system_prompt) -> Memory:
        self.memories[session_id] = Memory(system_prompt=system_prompt)
        return self.memories[session_id]


    def get_memory(self, session_id) -> Memory:
        return self.memories[session_id]

