BUSY_STATUS = "busy"
BUSY_RETRY_INTERVAL_S = 1.0


class WorkQueueLine:
    def __init__(self) -> None:
        self._waiting: dict[str, list[str]] = {}
        self._depth: dict[str, int] = {}

    def has_waiting(self, queue: str) -> bool:
        return bool(self._waiting.get(queue))

    def join(self, queue: str, task_id: str, depth: int) -> None:
        line = self._waiting.setdefault(queue, [])
        if task_id not in line:
            line.append(task_id)
        self._depth[queue] = depth

    def leave(self, queue: str, task_id: str) -> None:
        line = self._waiting.get(queue, [])
        if task_id in line:
            line.remove(task_id)
        if not line:
            self._waiting.pop(queue, None)
            self._depth.pop(queue, None)

    def record_depth(self, queue: str, depth: int) -> None:
        if self.has_waiting(queue):
            self._depth[queue] = depth

    def depth(self, queue: str) -> int:
        return self._depth.get(queue, 0)

    def ahead_of(self, queue: str, task_id: str) -> int:
        return self._waiting.get(queue, []).index(task_id)

    def position(self, queue: str, task_id: str) -> int:
        return self.depth(queue) + self.ahead_of(queue, task_id) + 1


work_queue_line = WorkQueueLine()
