// ===== State =====
let todos = [];
let currentFilter = "all";

// ===== DOM =====
const todoInput = document.getElementById("todoInput");
const addBtn = document.getElementById("addBtn");
const todoList = document.getElementById("todoList");
const itemCount = document.getElementById("itemCount");
const clearCompletedBtn = document.getElementById("clearCompleted");
const dateDisplay = document.getElementById("dateDisplay");
const filterBtns = document.querySelectorAll(".filter-btn");

// ===== Init =====
document.addEventListener("DOMContentLoaded", () => {
  loadTodos();
  render();
  showDate();
});

function showDate() {
  const now = new Date();
  const options = { weekday: "long", month: "long", day: "numeric" };
  dateDisplay.textContent = now.toLocaleDateString("en-US", options);
}

// ===== Storage =====
function loadTodos() {
  const stored = localStorage.getItem("todos");
  if (stored) {
    try {
      todos = JSON.parse(stored);
    } catch {
      todos = [];
    }
  }
}

function saveTodos() {
  localStorage.setItem("todos", JSON.stringify(todos));
}

// ===== CRUD =====
function addTodo(text) {
  text = text.trim();
  if (!text) return;

  todos.push({
    id: Date.now().toString(),
    text,
    completed: false,
    createdAt: new Date().toISOString(),
  });

  saveTodos();
  render();
  todoInput.value = "";
  todoInput.focus();
}

function deleteTodo(id) {
  todos = todos.filter((t) => t.id !== id);
  saveTodos();
  render();
}

function toggleTodo(id) {
  const todo = todos.find((t) => t.id === id);
  if (todo) {
    todo.completed = !todo.completed;
    saveTodos();
    render();
  }
}

function clearCompleted() {
  todos = todos.filter((t) => !t.completed);
  saveTodos();
  render();
}

// ===== Filtered View =====
function getFilteredTodos() {
  if (currentFilter === "active") {
    return todos.filter((t) => !t.completed);
  }
  if (currentFilter === "completed") {
    return todos.filter((t) => t.completed);
  }
  return todos;
}

// ===== Render =====
function render() {
  const filtered = getFilteredTodos();
  const activeCount = todos.filter((t) => !t.completed).length;

  // Update item count
  itemCount.textContent = `${activeCount} item${activeCount !== 1 ? "s" : ""} left`;

  // Clear list
  todoList.innerHTML = "";

  if (filtered.length === 0) {
    const empty = document.createElement("li");
    empty.className = "empty-state";
    empty.textContent = currentFilter === "all"
      ? "No tasks yet. Add one above! ✨"
      : currentFilter === "active"
      ? "No active tasks. 🎉"
      : "No completed tasks yet.";
    todoList.appendChild(empty);
    return;
  }

  filtered.forEach((todo) => {
    const li = document.createElement("li");
    li.className = "todo-item";
    li.dataset.id = todo.id;

    // Checkbox
    const checkbox = document.createElement("span");
    checkbox.className = `checkbox${todo.completed ? " checked" : ""}`;
    checkbox.addEventListener("click", () => toggleTodo(todo.id));

    // Text
    const textSpan = document.createElement("span");
    textSpan.className = `todo-text${todo.completed ? " completed" : ""}`;
    textSpan.textContent = todo.text;

    // Delete button
    const delBtn = document.createElement("button");
    delBtn.className = "delete-btn";
    delBtn.innerHTML = "✕";
    delBtn.setAttribute("aria-label", "Delete task");
    delBtn.addEventListener("click", () => deleteTodo(todo.id));

    li.appendChild(checkbox);
    li.appendChild(textSpan);
    li.appendChild(delBtn);
    todoList.appendChild(li);
  });
}

// ===== Events =====
addBtn.addEventListener("click", () => addTodo(todoInput.value));

todoInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    addTodo(todoInput.value);
  }
});

clearCompletedBtn.addEventListener("click", clearCompleted);

// Filter buttons
filterBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    filterBtns.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentFilter = btn.dataset.filter;
    render();
  });
});
