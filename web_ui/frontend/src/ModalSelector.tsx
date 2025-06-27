
import React, { useEffect } from "react";
import { withStreamlitConnection, Streamlit } from "streamlit-component-lib";

const ModalSelector = () => {
  useEffect(() => {
    Streamlit.setFrameHeight();
  }, []);

  const sendChoice = (choice: string) => {
    Streamlit.setComponentValue(choice);
  };

  return (
    <div style={{
      position: "fixed",
      top: 0, left: 0, width: "100vw", height: "100vh",
      backgroundColor: "rgba(0,0,0,0.5)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 9999
    }}>
      <div style={{ background: "#fff", padding: "2rem", borderRadius: "10px", textAlign: "center" }}>
        <h3>Select Output Type</h3>
        <button onClick={() => sendChoice("Video + Blog")}>Video + Blog</button>
        <button onClick={() => sendChoice("Video only")}>Video only</button>
        <button onClick={() => sendChoice("Blog only")}>Blog only</button>
      </div>
    </div>
  );
};

export default withStreamlitConnection(ModalSelector);
