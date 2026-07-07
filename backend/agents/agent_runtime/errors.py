from __future__ import annotations


class AgentRuntimeLoopError(RuntimeError):
  pass


class TargetedUpdateNoMatchError(AgentRuntimeLoopError):
  pass


class UpdateRequestNeedsClarificationError(TargetedUpdateNoMatchError):
  pass


class ScopedUpdateGuardError(TargetedUpdateNoMatchError):
  pass
