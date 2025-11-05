import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
// если нет файла styles.css — УДАЛИ эту строку ниже
// import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
