import React from "react";
import { BrowserRouter as Router, useLocation } from "react-router-dom";
import Home from "./components/Home";
import { ThemeProvider } from "./theme/ThemeContext";
import { LanguageProvider } from "./context/LanguageContext";
import MarketView from "./features/market/MarketView";
import DiseaseDetector from "./features/Disease/DiseaseDetector";
import VoiceControl from "./features/voice/VoiceControl";
import YieldPredictor from "./features/yield/YieldPredictor";
import ChatAssistant from "./features/chat/ChatAssistant";
import Navbar from "./components/Navbar";
import Microfarm from "./features/microfarm/Microfarm";

function AppContent() {
  const location = useLocation();
  const pathname = location.pathname;

  return (
    <>
      <Navbar />
      <div style={{ display: pathname === "/" ? "block" : "none" }}>
        <Home />
      </div>
      <div style={{ display: pathname === "/market" ? "block" : "none" }}>
        <MarketView />
      </div>
      <div style={{ display: pathname === "/disease" ? "block" : "none" }}>
        <DiseaseDetector />
      </div>
      <div style={{ display: pathname === "/voice" ? "block" : "none" }}>
        <VoiceControl />
      </div>
      <div style={{ display: pathname === "/yield" ? "block" : "none" }}>
        <YieldPredictor />
      </div>
      <div style={{ display: pathname === "/chat" ? "block" : "none" }}>
        <ChatAssistant />
      </div>
      <div style={{ display: pathname === "/microfarm" ? "block" : "none" }}>
        <Microfarm />
      </div>
    </>
  );
}

function App() {
  return (
    <ThemeProvider>
      <LanguageProvider>
        <Router>
          <AppContent />
        </Router>
      </LanguageProvider>
    </ThemeProvider>
  );
}

export default App;