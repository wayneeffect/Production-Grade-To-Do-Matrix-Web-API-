import json
import os
import logging
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# --- Configuration & Logging Setup ---
TODO_FILE = "todo_list.json"
LOG_FILE = "todo_app.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# --- Core Domain & Data Access Layer ---
class TaskManager:
    """Handles business logic and atomic data persistence for the to-do list."""
    def __init__(self, file_path: str = TODO_FILE):
        self.file_path = file_path
        self.tasks: List[Dict[str, Any]] = []
        self.load_tasks()

    def _validate_schema(self, data: Any) -> bool:
        if not isinstance(data, list):
            return False
        for item in data:
            if not isinstance(item, dict) or "title" not in item or "completed" not in item:
                return False
            if not isinstance(item["title"], str) or not isinstance(item["completed"], bool):
                return False
        return True

    def load_tasks(self) -> None:
        if not os.path.exists(self.file_path):
            self.tasks = []
            return
        try:
            with open(self.file_path, "r", encoding="utf-8") as file:
                data = json.load(file)
                if self._validate_schema(data):
                    self.tasks = data
                    logging.info("Tasks successfully loaded from storage.")
                else:
                    logging.error("Data schema validation failed.")
                    self.tasks = []
        except (json.JSONDecodeError, IOError) as e:
            logging.error(f"Failed to read task file: {str(e)}")
            self.tasks = []

    def save_tasks_atomically(self) -> bool:
        temp_file = f"{self.file_path}.tmp"
        try:
            with open(temp_file, "w", encoding="utf-8") as file:
                json.dump(self.tasks, file, indent=4)
            os.replace(temp_file, self.file_path)
            logging.info("State successfully persisted atomically.")
            return True
        except IOError as e:
            logging.error(f"Atomic write operation failed: {str(e)}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
            return False

    def add_task(self, title: str) -> Optional[Dict[str, Any]]:
        sanitized_title = title.strip()
        if not sanitized_title:
            return None
        new_task = {"title": sanitized_title, "completed": False}
        self.tasks.append(new_task)
        if self.save_tasks_atomically():
            return new_task
        return None

    def complete_task(self, index: int) -> bool:
        if 0 <= index < len(self.tasks):
            self.tasks[index]["completed"] = True
            return self.save_tasks_atomically()
        return False

    def clear_completed_tasks(self) -> int:
        initial_count = len(self.tasks)
        self.tasks = [task for task in self.tasks if not task["completed"]]
        self.save_tasks_atomically()
        return initial_count - len(self.tasks)

# --- FastAPI Initialization & Pydantic Models ---
app = FastAPI(title="Production To-Do Matrix API")
manager = TaskManager(TODO_FILE)

class TaskPayload(BaseModel):
    title: str

# --- Web API Endpoints ---

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    """Serves the frontend user interface."""
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as file:
            return HTMLResponse(content=file.read(), status_code=200)
    return HTMLResponse(content="<h1>Frontend index.html missing</h1>", status_code=404)

@app.get("/api/tasks")
def get_tasks():
    """Returns the current validated task matrix."""
    return manager.tasks

@app.post("/api/tasks")
def add_task(payload: TaskPayload):
    """Appends a new verified task to the atomic state layer."""
    task = manager.add_task(payload.title)
    if not task:
        raise HTTPException(status_code=400, detail="Invalid payload content.")
    return {"status": "success", "task": task}

@app.post("/api/tasks/complete/{index}")
def complete_task(index: int):
    """Resolves an active state task by array index."""
    if manager.complete_task(index):
        return {"status": "success", "message": f"Index {index} resolved."}
    raise HTTPException(status_code=404, detail="Task index out of bounds.")

@app.post("/api/tasks/clear")
def clear_completed():
    """Triggers garbage collection on completed state items."""
    removed = manager.clear_completed_tasks()
    return {"status": "success", "cleared_count": removed}
