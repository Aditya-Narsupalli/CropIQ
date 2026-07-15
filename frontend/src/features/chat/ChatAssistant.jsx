import React, { useState, useRef, useEffect, useCallback } from "react";
// TTS/STT browser support check
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition || null;
const synth = window.speechSynthesis || null;
import { chatAssistantApi, multilingualChatApi, API_BASE_URL } from '../../services/api';
import { 
  FaPaperPlane, 
  FaSpinner, 
  FaLeaf, 
  FaSeedling, 
  FaCloudSun, 
  FaRegCheckCircle,
  FaShareAlt,
  FaMapMarkerAlt,
  FaInfoCircle,
  FaGlobe,
  FaMicrophone, 
  FaStopCircle,
  FaSearchLocation,
} from "react-icons/fa";
import { GiWheat, GiFarmTractor } from "react-icons/gi";
import { MdOutlineScience, MdOutlineWaterDrop } from "react-icons/md";
import { WiHumidity } from "react-icons/wi";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import LocationMapPicker from "../../components/LocationMapPicker";

// Custom icon component for consistency with theme
const FaChartLine = ({ className }) => (
  <svg 
    xmlns="http://www.w3.org/2000/svg" 
    className={className}
    viewBox="0 0 512 512"
    width="1em"
    height="1em"
    fill="currentColor"
  >
    <path d="M64 64c0-17.7-14.3-32-32-32S0 46.3 0 64V400c0 44.2 35.8 80 80 80H480c17.7 0 32-14.3 32-32s-14.3-32-32-32H80c-8.8 0-16-7.2-16-16V64zm406.6 86.6c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L320 210.7l-57.4-57.4c-12.5-12.5-32.8-12.5-45.3 0l-112 112c-12.5 12.5-12.5 32.8 0 45.3s32.8 12.5 45.3 0L240 221.3l57.4 57.4c12.5 12.5 32.8 12.5 45.3 0l128-128z"/>
  </svg>
);

// Custom agent icons that match theme
const AGENT_AVATARS = {
  general_assistant: <GiFarmTractor className="text-amber-600" />,
  market_expert: <FaChartLine className="text-blue-600" />,
  weather_advisor: <FaCloudSun className="text-sky-600" />,
  crop_doctor: <FaSeedling className="text-green-600" />
};

// Reusing FadeInSection component from YieldPredictor for consistency
const FadeInSection = ({ children, delay = 0 }) => {
  const [isVisible, setVisible] = useState(false);
  const domRef = useRef();

  useEffect(() => {
    const observer = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting) {
        setVisible(true);
        if (domRef.current) {
          observer.unobserve(domRef.current);
        }
      }
    });

    const currentRef = domRef.current;
    if (currentRef) observer.observe(currentRef);

    return () => {
      if (observer && currentRef) {
        observer.disconnect();
      }
    };
  }, []);

  return (
    <div
      ref={domRef}
      className={`transition-all duration-700 ease-out ${
        isVisible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-5"
      }`}
      style={{
        transitionDelay: `${delay}ms`,
      }}
    >
      {children}
    </div>
  );
};

// Tooltip component reused from YieldPredictor
const Tooltip = ({ content }) => {
  const [showTooltip, setShowTooltip] = useState(false);

  return (
    <div className="relative inline-block ml-2">
      <button
        type="button"
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        className="text-gray-400 hover:text-gray-600 focus:outline-none"
        aria-label="Information"
      >
        <FaInfoCircle className="text-sm" />
      </button>
      {showTooltip && (
        <div className="absolute z-10 w-48 p-2 mt-2 text-xs text-white bg-gray-800 rounded-md shadow-lg left-1/2 transform -translate-x-1/2">
          {content}
        </div>
      )}
    </div>
  );
};

function ChatAssistant() {
  // TTS (Text-to-Speech) state
  const [ttsEnabled, setTtsEnabled] = useState(true);
  // STT (Speech-to-Text) mode: 'browser' (Web Speech API) or 'upload' (record & send)
  const [sttMode, setSttMode] = useState(SpeechRecognition ? 'browser' : 'upload');
  const [recognitionActive, setRecognitionActive] = useState(false);
  const recognitionRef = useRef(null);
  const [recording, setRecording] = useState(false);
  const [mediaRecorder, setMediaRecorder] = useState(null);
  const [audioChunks, setAudioChunks] = useState([]);
  const [audioUrl, setAudioUrl] = useState(null);
  const audioPlayerRef = useRef(null);

  // Start recording audio
  const handleStartRecording = async () => {
    setError("");
    setAudioUrl(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new window.MediaRecorder(stream);
      setMediaRecorder(recorder);
      setAudioChunks([]);
      recorder.start();
      setRecording(true);
      recorder.ondataavailable = (e) => {
        setAudioChunks((prev) => [...prev, e.data]);
      };
      recorder.onstop = async () => {
        setRecording(false);
        const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
        await handleSendAudio(audioBlob);
        stream.getTracks().forEach(track => track.stop());
      };
    } catch {
      setError("🎤 Microphone access denied or unavailable.");
    }
  };

  // Stop recording
  const handleStopRecording = () => {
    if (mediaRecorder) {
      mediaRecorder.stop();
      setMediaRecorder(null);
    }
  };

  // Send audio to backend and play response
  const handleSendAudio = async (audioBlob) => {
    setLoading(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append('file', audioBlob, 'input.wav');
      formData.append('language', selectedLanguage);
      const response = await fetch(`${API_BASE_URL}/chat/speech-chat`, {
        method: 'POST',
        body: formData
      });
      let data;
      try {
        data = await response.json();
      } catch (err) {
        setError("Speech chat: Invalid server response (not JSON). Check backend.");
        console.error("Speech chat: Invalid JSON response", err);
        return;
      }
      console.log("Speech chat backend response:", data);
      if (!response.ok) {
        setError(`Speech chat failed: ${data?.detail || response.statusText}`);
        return;
      }
      if (!data.user_transcript) {
        setError("Speech chat: No transcript returned from backend. Check backend implementation.");
        return;
      }
      setInput(data.user_transcript);
      setSpeechCaptured(true);
      setTimeout(() => inputRef.current?.focus(), 100);
      // DO NOT send to AI automatically; user must review and click Send
    } catch {
      setError("Failed to get audio reply from AI.");
    } finally {
      setLoading(false);
    }
  };

  // Helper to convert base64 to Blob
  function b64toBlob(b64Data, contentType = '', sliceSize = 512) {
    const byteCharacters = atob(b64Data);
    const byteArrays = [];
    for (let offset = 0; offset < byteCharacters.length; offset += sliceSize) {
      const slice = byteCharacters.slice(offset, offset + sliceSize);
      const byteNumbers = new Array(slice.length);
      for (let i = 0; i < slice.length; i++) {
        byteNumbers[i] = slice.charCodeAt(i);
      }
      const byteArray = new Uint8Array(byteNumbers);
      byteArrays.push(byteArray);
    }
    return new Blob(byteArrays, { type: contentType });
  }

  const [input, setInput] = useState("");
  const [speechCaptured, setSpeechCaptured] = useState(false);
  const inputRef = useRef(null);
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content: "Welcome to CropIQ AI! I'm here to assist with all your agricultural needs - from crop management and weather insights to market trends and farming advice. How can I help your farm thrive today?"
    }
  ]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedAgent, setSelectedAgent] = useState("crop_doctor");
  const [selectedLanguage, setSelectedLanguage] = useState("en");
  const [location, setLocation] = useState("");
  const [latitude, setLatitude] = useState(19.2183);
  const [longitude, setLongitude] = useState(73.8197);
  const [autoLocationEnabled, setAutoLocationEnabled] = useState(false);
  const [gettingLocation, setGettingLocation] = useState(false);
  const [weather, setWeather] = useState(null);
  const [gettingWeather, setGettingWeather] = useState(false);
  const [showMap, setShowMap] = useState(false);
  const [locationSelected, setLocationSelected] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const chatEndRef = useRef(null);

  const formatLocationLabel = useCallback((addressData, fallbackLat, fallbackLng) => {
    const address = addressData?.address || addressData || {};
    const city =
      address.city ||
      address.town ||
      address.village ||
      address.municipality ||
      address.hamlet ||
      address.suburb ||
      address.county ||
      "";
    const district =
      address.county ||
      address.district ||
      address.state_district ||
      address.city_district ||
      "";
    const country = address.country || "";

    const parts = [];
    if (city) parts.push(city);
    if (district && district.toLowerCase() !== city.toLowerCase()) parts.push(district);
    if (country) parts.push(country);

    if (parts.length > 0) {
      return parts.join(", ");
    }

    return `${(fallbackLat ?? 0).toFixed(4)}, ${(fallbackLng ?? 0).toFixed(4)}`;
  }, []);

  const agentOptions = [
    { value: "general_assistant", label: "Farm Assistant", icon: <GiFarmTractor /> },
    { value: "market_expert", label: "Market Expert", icon: <FaChartLine /> },
    { value: "weather_advisor", label: "Weather Advisor", icon: <FaCloudSun /> },
    { value: "crop_doctor", label: "Crop Doctor", icon: <FaSeedling /> },
  ];

  const languageOptions = [
    { value: "en", label: "English" },
    { value: "hi", label: "हिंदी (Hindi)" },
    { value: "mr", label: "मराठी (Marathi)" },
    { value: "gu", label: "ગુજરાતી (Gujarati)" },
    { value: "pa", label: "ਪੰਜਾਬੀ (Punjabi)" },
    { value: "bn", label: "বাংলা (Bengali)" },
    { value: "te", label: "తెలుగు (Telugu)" },
    { value: "ta", label: "தமிழ் (Tamil)" },
    { value: "kn", label: "ಕನ್ನಡ (Kannada)" },
    { value: "ml", label: "മലയാളം (Malayalam)" }
  ];

  const activeAgent = agentOptions.find((agent) => agent.value === selectedAgent) || agentOptions[0];

  // Scroll to bottom of chat when messages update
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // TTS: Speak text using browser API
  function speakText(text) {
    if (!synth || !ttsEnabled) return;
    synth.cancel(); // stop any previous
    const utter = new window.SpeechSynthesisUtterance(text);
    utter.lang = selectedLanguage === 'en' ? 'en-US' : selectedLanguage;
    utter.rate = 1.05;
    synth.speak(utter);
  }

  // STT: Start browser speech recognition
  const handleStartRecognition = () => {
    if (!SpeechRecognition) return;
    setRecognitionActive(true);
    const recognition = new SpeechRecognition();
    recognition.lang = selectedLanguage === 'en' ? 'en-US' : selectedLanguage;
    recognition.interimResults = true;
    recognition.continuous = false;
    recognitionRef.current = recognition;
    recognition.onresult = (event) => {
      let transcript = '';
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        transcript += event.results[i][0].transcript;
      }
      setInput(transcript);
      setSpeechCaptured(true);
      setTimeout(() => inputRef.current?.focus(), 100);
      // Ensure input is updated even if interim results (for live STT)
      if (!event.results[event.results.length - 1].isFinal) {
        inputRef.current?.focus();
      }
      if (event.results[event.results.length - 1].isFinal) {
        setRecognitionActive(false);
        recognition.stop();
        // Optionally auto-send:
        // handleSend({ preventDefault: () => {} });
      }
    };
    recognition.onerror = () => setRecognitionActive(false);
    recognition.onend = () => setRecognitionActive(false);
    recognition.start();
  };

  // STT: Stop browser speech recognition
  const handleStopRecognition = () => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      setRecognitionActive(false);
    }
  };

  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;
    
    setError("");
    setLoading(true);
    
    const newMessages = [...messages, { role: "user", content: input }];
    setMessages(newMessages);
    setInput("");
    setSpeechCaptured(false);
    
    try {
      // Use multilingual API if a non-English language is selected, otherwise use regular chat API
      if (selectedLanguage !== "en") {
        const data = await multilingualChatApi({
          message: input,
          session_id: sessionId,
          language: selectedLanguage,
          location: location
        });
        
        // Store session ID for conversation continuity
        if (!sessionId) {
          setSessionId(data.session_id);
        }
        
        setMessages([...newMessages, { role: "assistant", content: data.response || "(No response)" }]);
      } else {
        const data = await chatAssistantApi({
          message: input,
          history: newMessages.filter(m => m.role !== 'error').map(m => ({ role: m.role, content: m.content })),
          agent: selectedAgent,
          location: location
        });
        
        setMessages([...newMessages, { role: "assistant", content: data.response || "(No response)" }]);
      }
    } catch {
      let errorMsg = "An error occurred.";
      
      setMessages([
        ...newMessages,
        {
          role: "error",
          content: errorMsg,
          retry: false
        }
      ]);
      
      setError(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  const handleShare = () => {
    const text = messages.map(m => {
      const prefix = m.role === 'user' ? '👤' : m.role === 'assistant' ? '🤖' : '⚠️';
      return `${prefix} ${m.content}`;
    }).join('\n\n');
    
    if (navigator.share) {
      navigator.share({ title: 'CropIQ Chat', text });
    } else {
      navigator.clipboard.writeText(text);
      alert("Conversation copied to clipboard!");
    }
  };

  // Handle agent change
  const handleAgentChange = (e) => {
    const newAgent = e.target.value;
    setSelectedAgent(newAgent);
    
    // Add system message indicating agent change
    const selectedAgentInfo = agentOptions.find(a => a.value === newAgent);
    setMessages([
      ...messages,
      { 
        role: "system", 
        content: `Switching to ${selectedAgentInfo?.label || 'Assistant'} mode. How can I help you?` 
      }
    ]);
  };
  
  // Handle language change
  const handleLanguageChange = (e) => {
    const newLanguage = e.target.value;
    setSelectedLanguage(newLanguage);
    
    // Reset session ID when language changes to start fresh conversation
    setSessionId(null);
    
    // Add system message indicating language change
    const selectedLanguageInfo = languageOptions.find(l => l.value === newLanguage);
    setMessages([
      ...messages,
      { 
        role: "system", 
        content: `Switching to ${selectedLanguageInfo?.label || 'English'} language. How can I help you?` 
      }
    ]);
  };

  // Handle auto location
  const fetchWeatherData = useCallback(async (latitude, longitude) => {
    setGettingWeather(true);
    try {
      const response = await fetch(
        `https://api.open-meteo.com/v1/forecast?latitude=${latitude}&longitude=${longitude}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m&timezone=auto`
      );
      const data = await response.json();
      if (data.current) {
        setWeather({
          temperature: data.current.temperature_2m,
          humidity: data.current.relative_humidity_2m,
          windSpeed: data.current.wind_speed_10m,
          weatherCode: data.current.weather_code,
          timezone: data.timezone
        });
      }
    } catch (err) {
      console.error("Failed to fetch weather:", err);
    } finally {
      setGettingWeather(false);
    }
  }, []);

  const handleAutoLocation = useCallback(async () => {
    setGettingLocation(true);
    if (!navigator.geolocation) {
      setError("Geolocation is not supported by your browser.");
      setGettingLocation(false);
      return;
    }

    navigator.geolocation.getCurrentPosition(
      async (position) => {
        const { latitude, longitude } = position.coords;
        try {
          const response = await fetch(
            `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${latitude}&lon=${longitude}`
          );
          const data = await response.json();
          const locationName = formatLocationLabel(data, latitude, longitude);
          setLocation(locationName);
          setLatitude(latitude);
          setLongitude(longitude);
          setLocationSelected(true);
          setAutoLocationEnabled(true);
          setError("");
          await fetchWeatherData(latitude, longitude);
        } catch (err) {
          const fallbackLocationName = formatLocationLabel(null, latitude, longitude);
          setLocation(fallbackLocationName);
          setLatitude(latitude);
          setLongitude(longitude);
          setLocationSelected(true);
          setAutoLocationEnabled(true);
          setError("");
          await fetchWeatherData(latitude, longitude);
        } finally {
          setGettingLocation(false);
        }
      },
      (error) => {
        setError(`Location access denied: ${error.message}`);
        setGettingLocation(false);
      }
    );
  }, [fetchWeatherData, formatLocationLabel]);


  // Handle quick question selection
  const handleQuickQuestion = (question) => {
    setInput(question);
    // Focus the input field
    document.querySelector('input[type="text"]').focus();
  };

  return (
    <div className="min-h-screen bg-[linear-gradient(135deg,_#f9fff6_0%,_#f2fef0_45%,_#fffdf2_100%)] pt-20 pb-12 flex flex-col items-center justify-center px-4 relative overflow-hidden">
      {/* Soft background accents */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none z-0">
        <div className="absolute -top-20 left-0 h-72 w-72 rounded-full bg-green-200/50 blur-3xl" />
        <div className="absolute bottom-0 right-0 h-80 w-80 rounded-full bg-amber-200/50 blur-3xl" />
        {/* Subtle wheat accents */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <GiWheat
            className="absolute text-amber-400 text-4xl"
            style={{
              right: "10%",
              top: "15%",
              opacity: 0.15,
              transform: "rotate(45deg) scale(2.5)",
            }}
          />
          <GiWheat
            className="absolute text-amber-400 text-4xl"
            style={{
              left: "8%",
              bottom: "20%",
              opacity: 0.12,
              transform: "rotate(-65deg) scale(2)",
            }}
          />
          <GiWheat
            className="absolute text-amber-400 text-4xl"
            style={{
              right: "15%",
              top: "50%",
              opacity: 0.1,
              transform: "rotate(120deg) scale(3)",
            }}
          />
          <GiWheat
            className="absolute text-amber-400 text-4xl"
            style={{
              left: "20%",
              top: "10%",
              opacity: 0.08,
              transform: "rotate(20deg) scale(1.5)",
            }}
          />
          <GiWheat
            className="absolute text-amber-400 text-4xl"
            style={{
              right: "25%",
              bottom: "12%",
              opacity: 0.07,
              transform: "rotate(-20deg) scale(1.7)",
            }}
          />
        </div>

        {/* Subtle leaf accents */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <FaLeaf
            className="absolute text-green-400 text-4xl"
            style={{
              left: "5%",
              top: "8%",
              opacity: 0.1,
              transform: "rotate(-30deg) scale(2.0)",
            }}
          />
          <FaLeaf
            className="absolute text-green-400 text-4xl"
            style={{
              left: "15%",
              bottom: "45%",
              opacity: 0.09,
              transform: "rotate(75deg) scale(1.8)",
            }}
          />
          <FaLeaf
            className="absolute text-green-400 text-4xl"
            style={{
              right: "35%",
              bottom: "5%",
              opacity: 0.08,
              transform: "rotate(-15deg) scale(2.2)",
            }}
          />
          <FaLeaf
            className="absolute text-green-400 text-4xl"
            style={{
              right: "20%",
              top: "8%",
              opacity: 0.07,
              transform: "rotate(55deg) scale(1.6)",
            }}
          />
          <FaLeaf
            className="absolute text-green-400 text-4xl"
            style={{
              right: "5%",
              bottom: "8%",
              opacity: 0.11,
              transform: "rotate(25deg) scale(2.1)",
            }}
          />
        </div>
      </div>

      {/* Page Header */}
      <div className="w-full max-w-4xl mb-8 relative z-10">
        <FadeInSection>
          <div className="rounded-[28px] border border-green-200/70 bg-gradient-to-r from-green-800 via-emerald-700 to-green-700 p-6 md:p-8 text-white shadow-[0_25px_90px_-25px_rgba(22,101,52,0.65)]">
            <div className="inline-flex p-3 rounded-full bg-white/15 backdrop-blur-sm mb-4">
              <GiFarmTractor className="text-3xl" />
            </div>
            <h1 className="text-3xl md:text-4xl font-extrabold mb-2">
              CropIQ AI Chat
            </h1>
            <p className="text-green-50 max-w-2xl text-sm md:text-base">
              Get personalized agricultural advice, weather insights, and farming recommendations from your expert Crop Doctor.
            </p>
            <div className="mt-4 inline-flex items-center rounded-full bg-white/15 px-3 py-1 text-sm font-medium">
              {activeAgent?.label || "Crop Doctor"} mode is active
            </div>
          </div>
        </FadeInSection>
      </div>

      {/* Main Chat Container */}
      <div className="w-full max-w-4xl relative z-10">
        <FadeInSection delay={150}>
          <div className="bg-white/95 backdrop-blur-sm rounded-[24px] shadow-[0_24px_80px_-25px_rgba(0,0,0,0.35)] p-6 border border-green-100 transform transition-all duration-300 hover:shadow-[0_28px_90px_-22px_rgba(0,0,0,0.4)] relative overflow-hidden">
            {/* Subtle background pattern */}
            <div className="absolute top-0 left-0 w-full h-full opacity-5 pointer-events-none">
              <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
                <pattern
                  id="pattern-chat"
                  x="0"
                  y="0"
                  width="20"
                  height="20"
                  patternUnits="userSpaceOnUse"
                >
                  <circle cx="2" cy="2" r="1" fill="#fcd34d" />
                </pattern>
                <rect
                  x="0"
                  y="0"
                  width="100%"
                  height="100%"
                  fill="url(#pattern-chat)"
                />
              </svg>
            </div>

            {/* Chat Header */}
            <div className="flex items-center justify-between mb-6 border-b pb-4 border-gray-100 relative z-10">
              <div className="flex items-center space-x-3">
                <div className="bg-amber-100 p-2 rounded-full">
                  {activeAgent?.icon || <GiFarmTractor className="text-amber-600 text-xl" />}
                </div>
                <h3 className="text-xl font-semibold text-gray-800">
                  {activeAgent?.label || 'Farm Assistant'}
                </h3>
              </div>
              <div className="flex items-center space-x-3">
                <div className="relative">
                  <select
                    value={selectedAgent}
                    onChange={handleAgentChange}
                    className="pl-3 pr-8 py-2 border border-amber-200 rounded-lg focus:ring-2 focus:ring-amber-300 focus:border-amber-300 bg-white text-gray-700 text-sm appearance-none cursor-pointer transition-colors hover:border-amber-400"
                    aria-label="Choose Expert Agent"
                    disabled={selectedLanguage !== "en"}
                  >
                    {agentOptions.map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                  <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-amber-600">
                    <svg className="w-4 h-4 fill-current" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
                      <path d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" />
                    </svg>
                  </div>
                </div>

                {/* Location Input with Auto-detect */}
                <div className="flex flex-col gap-2 w-full">
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      id="auto-location-chat"
                      checked={autoLocationEnabled}
                      onChange={(e) => {
                        if (e.target.checked) {
                          handleAutoLocation();
                        } else {
                          setAutoLocationEnabled(false);
                          setWeather(null);
                        }
                      }}
                      disabled={gettingLocation || gettingWeather}
                      className="w-4 h-4 rounded border-gray-300 cursor-pointer"
                    />
                    <label htmlFor="auto-location-chat" className="text-sm text-gray-700 cursor-pointer">
                      Enable auto location
                    </label>
                    {(gettingLocation || gettingWeather) && (
                      <FaSpinner className="animate-spin text-amber-600 text-sm ml-2" />
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowMap(!showMap)}
                    className="flex items-center px-3 py-2 bg-blue-100 text-blue-700 text-sm rounded-lg hover:bg-blue-200 transition-colors shadow-sm"
                  >
                    <FaSearchLocation className="mr-2" />
                    {showMap ? "Hide Map" : "Select on Map"}
                  </button>
                  {locationSelected && location && (
                    <div className="flex items-start gap-2 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
                      <FaMapMarkerAlt className="mt-0.5 text-green-600 flex-shrink-0" />
                      <div>
                        <div className="font-medium">Selected location</div>
                        <div className="text-green-700">{location}</div>
                      </div>
                    </div>
                  )}
                  {showMap && (
                    <FadeInSection>
                      <div className="mt-2 space-y-3 p-4 bg-gray-50 rounded-lg border">
                        <LocationMapPicker
                          latitude={latitude}
                          longitude={longitude}
                          location={location}
                          onLocationChange={(value) => {
                            setLocation(value);
                            setLocationSelected(Boolean(value));
                          }}
                          onCoordinatesChange={(lat, lng) => {
                            setLatitude(lat);
                            setLongitude(lng);
                            setLocationSelected(true);
                            fetchWeatherData(lat, lng);
                          }}
                          onWeatherRefresh={fetchWeatherData}
                        />
                      </div>
                    </FadeInSection>
                  )}
                  {weather && (
                    <div className="mt-2 p-3 bg-blue-50 rounded border border-blue-200 text-sm space-y-1">
                      <div className="text-blue-900 font-medium">📍 Current Weather</div>
                      <div className="text-blue-700">🌡️ Temperature: <span className="font-medium">{weather.temperature}°C</span></div>
                      <div className="text-blue-700">💧 Humidity: <span className="font-medium">{weather.humidity}%</span></div>
                      <div className="text-blue-700">💨 Wind Speed: <span className="font-medium">{weather.windSpeed} km/h</span></div>
                    </div>
                  )}
                </div>

                <button
                  onClick={handleShare}
                  className="flex items-center px-3 py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-green-300"
                  aria-label="Share conversation"
                  title="Share conversation"
                >
                  <FaShareAlt className="mr-2" />
                  Share
                </button>
              </div>
            </div>

            {/* Chat Messages */}
            <div className="h-96 md:h-[28rem] overflow-y-auto mb-4 px-3 py-3 relative z-10 space-y-4 rounded-2xl border border-green-100 bg-[linear-gradient(135deg,_#fafff6_0%,_#f4ffe8_100%)]">
              {messages.map((msg, idx) => (
                <FadeInSection key={idx} delay={idx * 50}>
                  <div
                    className={`flex ${
                      msg.role === "user" ? "justify-end" : "justify-start"
                    } ${msg.role === "system" ? "opacity-70" : ""}`}
                  >
                    {msg.role !== "user" && msg.role !== "system" && (
                      <div className="w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center mr-2 flex-shrink-0 self-end mb-2">
                        {AGENT_AVATARS[selectedAgent] || <GiFarmTractor className="text-amber-600" />}
                      </div>
                    )}
                    <div
                      className={`max-w-[80%] p-3 rounded-xl shadow-sm ${
                        msg.role === "user"
                          ? "bg-green-600 text-white rounded-br-none"
                          : msg.role === "assistant"
                          ? "bg-white border border-amber-100 rounded-bl-none"
                          : msg.role === "system"
                          ? "bg-gray-100 text-gray-600 text-sm italic"
                          : "bg-red-50 border-l-4 border-red-500 text-red-700"
                      }`}
                    >
                      <ReactMarkdown
                        children={msg.content}
                        remarkPlugins={[remarkGfm]}
                        components={{
                          a: (props) => (
                            <a {...props} target="_blank" rel="noopener noreferrer" className="text-amber-600 hover:text-amber-700 underline" />
                          ),
                          code: (props) => (
                            <code {...props} className="bg-amber-50 text-amber-800 rounded px-1 py-0.5 text-sm" />
                          ),
                          pre: (props) => (
                            <pre {...props} className="bg-gray-50 rounded-md p-3 text-sm overflow-x-auto my-2" />
                          ),
                          ul: (props) => (
                            <ul {...props} className="list-disc pl-5 space-y-1 my-2" />
                          ),
                          ol: (props) => (
                            <ol {...props} className="list-decimal pl-5 space-y-1 my-2" />
                          ),
                          li: (props) => (
                            <li {...props} className="ml-2" />
                          ),
                          p: (props) => (
                            <p {...props} className="mb-2 last:mb-0" />
                          ),
                          h1: (props) => (
                            <h1 {...props} className="text-lg font-bold mb-2" />
                          ),
                          h2: (props) => (
                            <h2 {...props} className="text-md font-bold mb-2" />
                          ),
                          h3: (props) => (
                            <h3 {...props} className="text-base font-bold mb-1" />
                          ),
                        }}
                      />
                      {/* Read Aloud button for AI responses */}
                      {msg.role === "assistant" && (
                        <button
                          className="mt-2 ml-2 px-3 py-1 bg-amber-100 hover:bg-amber-200 text-amber-800 text-xs rounded-md flex items-center transition-colors"
                          onClick={() => speakText(msg.content)}
                          aria-label="Read aloud"
                          title="Read aloud"
                        >
                          <FaMicrophone className="mr-1 text-amber-600" /> Read Aloud
                        </button>
                      )}
                      {msg.retry && (
                        <button
                          className="mt-3 px-3 py-1 bg-red-500 hover:bg-red-600 text-white text-sm rounded-md flex items-center transition-colors"
                          onClick={() => window.location.reload()}
                        >
                          <FaRegCheckCircle className="mr-1.5" /> Retry
                        </button>
                      )}
                    </div>
                    {msg.role === "user" && (
                      <div className="w-8 h-8 rounded-full bg-green-100 flex items-center justify-center ml-2 flex-shrink-0 self-end mb-2">
                        <FaMapMarkerAlt className="text-green-600" />
                      </div>
                    )}
                  </div>
                </FadeInSection>
              ))}
            </div>
            <div ref={chatEndRef} />

            {/* Input Area */}
            <div className="chat-footer flex items-center gap-2 bg-gradient-to-r from-white to-green-50 rounded-2xl border border-green-100 px-3 py-3 mt-3 sticky bottom-0 z-20 shadow-sm">
              <input
                ref={inputRef}
                type="text"
                className="flex-1 px-3 py-2 rounded-lg border border-gray-200 focus:border-green-400 focus:ring-2 focus:ring-green-100 text-base"
                placeholder="Type your message..."
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  if (speechCaptured) setSpeechCaptured(false);
                }}
                onKeyDown={(e) => e.key === 'Enter' && handleSend(e)}
                disabled={loading}
                style={{ minWidth: 0 }}
              />
              <button
                className="flex items-center justify-center h-10 w-10 rounded-lg bg-green-600 text-white hover:bg-green-700 transition"
                onClick={recognitionActive ? handleStopRecognition : handleStartRecognition}
                disabled={loading}
                aria-label={recognitionActive ? "Stop speech recognition" : "Start speech recognition"}
                title="Voice input"
              >
                {recognitionActive ? <FaStopCircle /> : <FaMicrophone />}
              </button>
              <button
                className="flex items-center justify-center h-10 w-10 rounded-lg bg-green-600 text-white hover:bg-green-700 transition"
                onClick={handleSend}
                disabled={loading || !input.trim()}
                aria-label="Send"
              >
                {loading ? <FaSpinner className="animate-spin" /> : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
                  <path d="M22 2L11 13" />
                  <path d="M22 2L15 22L11 13L2 9L22 2Z" />
                </svg>}
              </button>
              {audioUrl && (
                <audio ref={audioPlayerRef} src={audioUrl} controls style={{ marginLeft: 8, height: 36 }} />
              )}
            </div>

             {/* Error message - prominent and spaced */}
             {error && (
               <div className="bg-red-50 border-l-4 border-red-500 p-4 mt-6 rounded-lg shadow flex items-start max-w-lg mx-auto">
                 <div className="text-red-500 mr-3 text-lg">⚠️</div>
                 <div className="text-sm text-red-700" dangerouslySetInnerHTML={{ __html: error }} />
               </div>
             )}

        </div>
      </FadeInSection>
    </div>

    {/* Footer with quick buttons */}
    <div className="w-full max-w-4xl mt-6 relative z-10">
      <FadeInSection delay={250}>
        <div className="text-center">
          <h4 className="text-sm font-medium mb-3 text-gray-600">Quick Questions</h4>
          <div className="flex flex-wrap justify-center gap-3">
            <button 
              onClick={() => handleQuickQuestion("What crops grow best in this season?")}
              className="px-4 py-2 bg-white hover:bg-green-50 border border-green-200 rounded-full text-xs md:text-sm text-gray-700 transition-colors hover:border-green-300 shadow-sm"
            >
              <FaSeedling className="inline mr-1.5 text-green-600" />
              Best seasonal crops
            </button>
            <button 
              onClick={() => handleQuickQuestion("How to improve soil fertility naturally?")}
              className="px-4 py-2 bg-white hover:bg-amber-50 border border-amber-200 rounded-full text-xs md:text-sm text-gray-700 transition-colors hover:border-amber-300 shadow-sm"
            >
              <MdOutlineScience className="inline mr-1.5 text-amber-600" />
              Soil improvement
            </button>
            <button 
              onClick={() => handleQuickQuestion("What's the current market price for wheat?")}
              className="px-4 py-2 bg-white hover:bg-blue-50 border border-blue-200 rounded-full text-xs md:text-sm text-gray-700 transition-colors hover:border-blue-300 shadow-sm"
            >
              <FaChartLine className="inline mr-1.5 text-blue-600" />
              Crop prices
            </button>
            <button 
              onClick={() => handleQuickQuestion("How will the weather affect my tomato crop?")}
              className="px-4 py-2 bg-white hover:bg-sky-50 border border-sky-200 rounded-full text-xs md:text-sm text-gray-700 transition-colors hover:border-sky-300 shadow-sm"
            >
              <FaCloudSun className="inline mr-1.5 text-sky-600" />
              Weather impact
            </button>
            <button 
              onClick={() => handleQuickQuestion("What's the best way to control pests organically?")}
              className="px-4 py-2 bg-white hover:bg-green-50 border border-green-200 rounded-full text-xs md:text-sm text-gray-700 transition-colors hover:border-green-300 shadow-sm"
            >
              <FaSeedling className="inline mr-1.5 text-green-600" />
              Organic pest control
            </button>
          </div>
        </div>
      </FadeInSection>
    </div>
    </div>
  );
}

export default ChatAssistant;