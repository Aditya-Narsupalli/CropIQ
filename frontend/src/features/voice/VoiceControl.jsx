import React, { useState } from "react";
import { useLanguage } from "../../context/LanguageContext";
import { processVoiceCommandApi } from '../../services/api';
import { FaMicrophone, FaSpinner, FaPaperPlane } from "react-icons/fa";
import { MdVoiceChat } from "react-icons/md";

const API_BASE = "http://localhost:8000/api/v1";

const VoiceControl = () => {
  const { t, language } = useLanguage();
  const [transcript, setTranscript] = useState("");
  const [response, setResponse] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setResponse("");

    try {
      const data = await processVoiceCommandApi({ transcript, language });
      setResponse(data.response_text || t("noResponseFromAI"));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };


  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-sky-50 to-cyan-50 pt-24 pb-12 px-4 flex items-center justify-center">
      <div className="max-w-xl w-full mx-auto p-6 bg-white rounded-xl shadow-lg border border-sky-100">
        <form onSubmit={handleSubmit}>
          <div className="text-center mb-6 relative">
            <div className="inline-flex p-3 bg-sky-100 rounded-full text-sky-800 mb-4">
              <MdVoiceChat className="text-3xl" />
            </div>
            <h2 className="text-2xl font-bold mb-2 text-slate-900">
              {t("voiceCommand")}
            </h2>
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <FaMicrophone className="text-gray-400" />
            </div>
            <input
              type="text"
              placeholder={t("enterTranscript")}
              value={transcript}
              onChange={(e) => setTranscript(e.target.value)}
              className="border border-gray-300 focus:border-sky-500 focus:ring-2 focus:ring-sky-200 pl-10 pr-3 py-2 rounded-lg w-full transition-all duration-300"
              required
            />
          </div>

          <div className="flex flex-wrap items-center gap-3 mb-4">
            <button
              type="submit"
              className="px-4 py-2 bg-sky-600 text-white rounded-lg hover:bg-sky-700 disabled:opacity-50 transition duration-300 flex items-center font-medium"
              disabled={loading}
            >
              {loading ? (
                <>
                  <FaSpinner className="animate-spin mr-2" />
                  {t("processing")}
                </>
              ) : (
                <>
                  <FaPaperPlane className="mr-2" />
                  {t("sendCommand")}
                </>
              )}
            </button>
          </div>
        </form>

        {error && (
          <div className="mb-6 p-4 bg-red-50 border-l-4 border-red-500 text-red-700 rounded-md">
            <p className="font-medium">{t("errorLabel")}: {error}</p>
          </div>
        )}

        {response && (
          <div className="bg-sky-50 p-5 rounded-lg border border-sky-200">
            <h3 className="font-semibold mb-2 text-sky-800">{t("aiResponse")}</h3>
            <div className="text-gray-700 whitespace-pre-line">{response}</div>
          </div>
        )}
      </div>
    </div>
  );
};

export default VoiceControl;

