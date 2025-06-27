import React from "react"
import { Streamlit, withStreamlitConnection, ComponentProps } from "streamlit-component-lib"

const ModalSelector = (props: ComponentProps) => {
  const sendChoice = (choice: string) => {
    console.log("User clicked choice:", choice)
    Streamlit.setComponentValue(choice)
  }

  React.useEffect(() => {
    console.log("📦 ModalSelector mounted")
  }, [])

  return (
    <div style={{
      position: "fixed",
      top: 0,
      left: 0,
      width: "100vw",
      height: "100vh",
      backgroundColor: "rgba(0, 0, 0, 0.5)",
      display: "flex",
      justifyContent: "center",
      alignItems: "center",
      zIndex: 9999
    }}>
      <div style={{
        backgroundColor: "#fff",
        padding: "24px",
        borderRadius: "12px",
        textAlign: "center",
        boxShadow: "0px 0px 20px rgba(0, 0, 0, 0.3)"
      }}>
        <h2>Select Output Type</h2>
        <button onClick={() => sendChoice("Video + Blog")}>Video + Blog</button>
        <button onClick={() => sendChoice("Video only")}>Video only</button>
        <button onClick={() => sendChoice("Blog only")}>Blog only</button>
      </div>
    </div>
  )
}

export default withStreamlitConnection(ModalSelector)
