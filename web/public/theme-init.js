// Apply the saved theme before the first paint (src/theme.ts keeps it up to date).
// A separate file, not inline, so the Content-Security-Policy can forbid inline scripts.
try {
  var t = localStorage.getItem("wamt.theme");
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
} catch (e) {}
