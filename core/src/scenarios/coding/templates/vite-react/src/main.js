import { items } from "./items.js";

const root = document.querySelector("#root");

function render(list = items) {
  root.innerHTML = `
    <section class="app-shell">
      <h1>Inventory</h1>
      <div class="toolbar">
        <input id="search" aria-label="Search items" placeholder="Search items" />
        <button id="toggle">Show selected</button>
      </div>
      <p id="counter">${list.length} items</p>
      <ul id="items">
        ${list.map((item) => `<li>${item}</li>`).join("")}
      </ul>
    </section>
  `;
}

render();

