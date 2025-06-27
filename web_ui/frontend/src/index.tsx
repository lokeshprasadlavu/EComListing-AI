import React from "react";
import ReactDOM from "react-dom/client";
import ModalSelector from "./ModalSelector";

const root = document.getElementById("root");
if (root) {
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <ModalSelector />
    </React.StrictMode>
  );
}
