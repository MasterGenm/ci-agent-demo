mermaid.initialize({ startOnLoad: true, securityLevel: "strict" });

const form = document.querySelector("#run-form");
if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button");
    button.disabled = true;
    button.textContent = "Running";
    const payload = Object.fromEntries(new FormData(form).entries());
    try {
      const response = await fetch("/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "run failed");
      }
      window.location.href = data.detail_url;
    } catch (error) {
      button.disabled = false;
      button.textContent = "Run";
      alert(error.message);
    }
  });
}
