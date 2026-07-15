import React, { useState, useEffect, useCallback, useRef } from "react";
import { detectDiseaseApi } from "../../services/api";
import { useLanguage } from "../../context/LanguageContext";
import {
  FaUpload,
  FaCamera,
  FaLeaf,
  FaSpinner,
  FaTimes,
  FaRegCheckCircle,
  FaInfoCircle,
  FaMapMarkerAlt,
  FaSearchLocation,
} from "react-icons/fa";
import { MdOutlineHealthAndSafety } from "react-icons/md";
import { GiWheat } from "react-icons/gi";
import { motion } from "framer-motion";
import LocationMapPicker from "../../components/LocationMapPicker";

// Fade in component for animation
const FadeInSection = ({ children, delay = 0 }) => {
  const [isVisible, setVisible] = useState(false);
  const domRef = React.useRef();

  useEffect(() => {
    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) {
        setVisible(true);
        observer.unobserve(domRef.current);
      }
    });

    if (domRef.current) {
      observer.observe(domRef.current);
    }

    return () => {
      if (domRef.current) {
        observer.disconnect();
      }
    };
  }, []);

  return (
    <div
      ref={domRef}
      className="transition-all duration-700 ease-out"
      style={{
        opacity: isVisible ? 1 : 0,
        transform: isVisible ? "none" : "translateY(20px)",
        transitionDelay: `${delay}ms`,
      }}
    >
      {children}
    </div>
  );
};

function DiseaseDetector() {
  const { t } = useLanguage();
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [analysisResult, setAnalysisResult] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(false);
  const [analysisStage, setAnalysisStage] = useState(0);
  const [progressPercent, setProgressPercent] = useState(0);
  
  // New state for crop context
  const [cropType, setCropType] = useState("tomato");
  const [location, setLocation] = useState("");
  const [latitude, setLatitude] = useState(19.2183);
  const [longitude, setLongitude] = useState(73.8197);
  const [autoLocationEnabled, setAutoLocationEnabled] = useState(false);
  const [gettingLocation, setGettingLocation] = useState(false);
  const [weather, setWeather] = useState(null);
  const [gettingWeather, setGettingWeather] = useState(false);
  const [showMap, setShowMap] = useState(false);
  const [locationSelected, setLocationSelected] = useState(false);

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

  // Get auto location using Geolocation API
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


  // Clean up preview URL
  useEffect(() => {
    if (file) {
      const objectUrl = URL.createObjectURL(file);
      setPreviewUrl(objectUrl);
      setUploadSuccess(true);
      setTimeout(() => setUploadSuccess(false), 2000);
      return () => URL.revokeObjectURL(objectUrl);
    }
    setPreviewUrl("");
  }, [file]);

  // Progress animation effect
  useEffect(() => {
    let interval;
    if (isLoading) {
      if (analysisStage === 1) {
        setProgressPercent(0);
        interval = setInterval(() => {
          setProgressPercent((prev) => Math.min(prev + 1, 45));
        }, 30);
      } else if (analysisStage === 2) {
        interval = setInterval(() => {
          setProgressPercent((prev) => Math.min(prev + 1, 90));
        }, 40);
      }
    } else {
      setProgressPercent(0);
    }
    return () => clearInterval(interval);
  }, [isLoading, analysisStage]);

  // Handle file input changes
  const handleFileChange = (event) => {
    const selectedFile = event.target.files?.[0];
    if (selectedFile) {
      if (!selectedFile.type.startsWith("image/")) {
        setError("Invalid file type. Please upload an image.");
        return;
      }
      if (selectedFile.size > 5 * 1024 * 1024) {
        setError("File is too large. Maximum size is 5MB.");
        return;
      }
      setFile(selectedFile);
      setAnalysisResult("");
      setError("");
      setAnalysisStage(0);
    }
  };

  // Handle drag events
  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) handleFileChange({ target: { files: [droppedFile] } });
  };

  // Handle analysis
  const handleAnalyzeClick = useCallback(async () => {
    if (!file) {
      setError("Please select an image file first.");
      return;
    }

    setIsLoading(true);
    setAnalysisResult("");
    setError("");
    setAnalysisStage(1);

    try {
      const result = await detectDiseaseApi(file, cropType, location);
      setTimeout(() => setAnalysisStage(2), 1500);

      setTimeout(() => {
        setProgressPercent(100);
        setAnalysisResult(result.analysis.replaceAll("*", ""));
        setAnalysisStage(3);
        setIsLoading(false);
      }, 1500);
    } catch (err) {
      setError(err.message || "An error occurred during analysis.");
      setIsLoading(false);
      setAnalysisStage(0);
    }
  }, [file, cropType, location]);

  // Handle clear
  const handleClear = () => {
    setFile(null);
    setPreviewUrl("");
    setAnalysisResult("");
    setError("");
    setAnalysisStage(0);
    const fileInput = document.getElementById("disease-image-upload");
    if (fileInput) fileInput.value = "";
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-50 via-sky-50 to-cyan-50 pt-24 pb-12 px-4">
      {/* Background decorative elements */}
      <div className="absolute top-0 left-0 w-full h-full overflow-hidden pointer-events-none z-0">
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
        </div>
      </div>

      <div className="max-w-7xl mx-auto relative z-10">
        {/* Header with symmetric icon */}
        <FadeInSection delay={100}>
          <div className="text-center mb-10 w-full">
            <motion.div
              animate={{
                y: [0, -5, 0],
                scale: [1, 1.05, 1],
              }}
              transition={{
                repeat: Infinity,
                duration: 3,
                ease: "easeInOut",
              }}
              className="inline-flex items-center justify-center p-5 bg-gradient-to-r from-amber-100 to-sky-100 rounded-full text-sky-600 mb-5 shadow-md mx-auto"
              style={{ width: "80px", height: "80px" }}
            >
              <MdOutlineHealthAndSafety className="text-4xl" />
            </motion.div>
            <h1 className="text-3xl md:text-4xl font-extrabold mb-3 text-slate-900 bg-clip-text text-transparent bg-gradient-to-r from-slate-900 to-sky-700">
              {t("diseaseDetectorTitle")}
            </h1>
            <p className="text-gray-600 max-w-xl md:max-w-2xl mx-auto text-sm md:text-base">
              {t("diseaseDetectorDescription")}
            </p>
          </div>
        </FadeInSection>

        {/* Main Content */}
        <FadeInSection delay={200}>
          <motion.div
            whileHover={{ y: -3 }}
            className="bg-white rounded-xl shadow-lg p-6 md:p-8 border border-amber-100 transition-all duration-300 hover:shadow-xl relative overflow-hidden"
          >
            {/* Subtle background pattern */}
            <div className="absolute top-0 left-0 w-full h-full opacity-5 pointer-events-none">
              <svg
                width="100%"
                height="100%"
                xmlns="http://www.w3.org/2000/svg"
              >
                <pattern
                  id="pattern-disease"
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
                  fill="url(#pattern-disease)"
                />
              </svg>
            </div>

            {!analysisResult ? (
              <div className="space-y-6">
                {/* Crop Context Form */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-5 bg-amber-50 rounded-lg border border-amber-200">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">Crop Type</label>
                    <select
                      value={cropType}
                      onChange={(e) => setCropType(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500"
                    >
                      <option value="tomato">Tomato</option>
                      <option value="wheat">Wheat</option>
                      <option value="rice">Rice</option>
                      <option value="corn">Corn</option>
                      <option value="potato">Potato</option>
                      <option value="onion">Onion</option>
                      <option value="lettuce">Lettuce</option>
                      <option value="cabbage">Cabbage</option>
                      <option value="chili">Chili</option>
                      <option value="other">Other</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      {t("locationLabelAlt")}
                      {locationSelected && (
                        <span className="ml-2 text-xs text-sky-600 font-medium">✓ {t("locationSet")}</span>
                      )}
                    </label>
                    <div className="mb-3 flex items-center gap-2">
                      <input
                        type="checkbox"
                        id="auto-location"
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
                      <label htmlFor="auto-location" className="text-sm text-gray-700 cursor-pointer">
                        {t("enableAutoLocation")}
                      </label>
                      {(gettingLocation || gettingWeather) && (
                        <FaSpinner className="animate-spin text-amber-600 text-sm ml-2" />
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => setShowMap(!showMap)}
                      className="flex items-center px-4 py-2 bg-blue-100 text-blue-700 text-sm rounded-lg hover:bg-blue-200 transition-colors shadow-sm mb-2"
                    >
                      <FaSearchLocation className="mr-2" />
                      {showMap ? t("hideMap") : t("selectOnMap")}
                    </button>
                    {locationSelected && (
                      <span className="text-xs text-sky-600 flex items-center ml-1">
                        <FaRegCheckCircle className="mr-1" /> {t("locationSet")}
                      </span>
                    )}
                    {locationSelected && location && (
                      <div className="mt-3 flex items-start gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-slate-800">
                        <FaMapMarkerAlt className="mt-0.5 text-sky-600 flex-shrink-0" />
                        <div>
                          <div className="font-medium">{t("selectedLocation")}</div>
                          <div className="text-sky-700">{location}</div>
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
                            onLocationChange={setLocation}
                            onCoordinatesChange={(lat, lng) => {
                              setLatitude(lat);
                              setLongitude(lng);
                              setLocationSelected(true);
                            }}
                            onWeatherRefresh={fetchWeatherData}
                          />
                        </div>
                      </FadeInSection>
                    )}
                    {weather && (
                      <div className="mt-3 p-3 bg-blue-50 rounded border border-blue-200 text-sm space-y-1">
                        <div className="text-blue-900 font-medium">{t("currentWeather")}</div>
                        <div className="text-blue-700">🌡️ {t("temperature")}: <span className="font-medium">{weather.temperature}°C</span></div>
                        <div className="text-blue-700">💧 {t("humidity")}: <span className="font-medium">{weather.humidity}%</span></div>
                        <div className="text-blue-700">💨 {t("windSpeed")}: <span className="font-medium">{weather.windSpeed} km/h</span></div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Upload Section */}
                <div
                  className={`p-8 border-2 border-dashed rounded-lg text-center transition-all duration-300 ${
                    isDragging
                      ? "border-sky-500 bg-sky-50"
                      : "border-gray-300 hover:border-sky-400"
                  }`}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                >
                  <input
                    type="file"
                    id="disease-image-upload"
                    accept="image/*"
                    onChange={handleFileChange}
                    className="hidden"
                    disabled={isLoading}
                  />

                  {!previewUrl ? (
                    <label
                      htmlFor="disease-image-upload"
                      className="flex flex-col items-center justify-center cursor-pointer w-full h-full py-8"
                    >
                      <div className="w-24 h-24 bg-gradient-to-r from-amber-100 to-sky-100 rounded-full flex items-center justify-center mb-6 shadow-md">
                        <FaUpload className="text-3xl text-amber-600" />
                      </div>
                      <span className="text-lg font-medium text-gray-700 mb-3">
                        {t("uploadPlantImage")}
                      </span>
                      <div className="flex items-center justify-center gap-3 text-sm">
                        <div className="flex items-center bg-amber-50 px-3 py-2 rounded-lg shadow-sm">
                          <FaUpload className="mr-2 text-amber-500" />
                          <span className="text-gray-600">{t("dragDrop")}</span>
                        </div>
                        <span className="text-gray-400">or</span>
                        <div className="flex items-center bg-sky-100 px-3 py-2 rounded-lg shadow-sm">
                          <FaCamera className="mr-2 text-sky-600" />
                          <span className="text-sky-700 font-medium">
                            {t("browseFiles")}
                          </span>
                        </div>
                      </div>
                    </label>
                  ) : (
                    <div className="relative py-4">
                      <div className="relative group mb-6">
                        <img
                          src={previewUrl}
                          alt="Selected plant preview"
                          className="max-h-56 object-contain mx-auto rounded-lg border border-gray-200 shadow-sm"
                        />
                      </div>
                      <div className="flex justify-center gap-4">
                        <button
                          onClick={handleClear}
                          disabled={isLoading}
                          className="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 disabled:opacity-50 transition-all duration-300 flex items-center shadow-sm"
                        >
                          <FaTimes className="mr-2" />
                          Clear
                        </button>
                        <button
                          onClick={handleAnalyzeClick}
                          disabled={isLoading || !file}
                          className="px-5 py-2 bg-gradient-to-r from-amber-500 to-amber-600 text-white rounded-lg font-medium hover:from-amber-600 hover:to-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-300 flex items-center shadow-sm"
                        >
                          {isLoading ? (
                            <>
                              <FaSpinner className="animate-spin mr-2" />
                              {analysisStage === 1 && t("processingImage")}
                              {analysisStage === 2 && t("analyzingPlantHealth")}
                            </>
                          ) : (
                            <>
                              <MdOutlineHealthAndSafety className="mr-2" />
                              {t("analyzeImage")}
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                  )}

                  {uploadSuccess && (
                    <div className="absolute inset-0 flex items-center justify-center bg-white bg-opacity-90 z-10">
                      <div className="text-sky-500 text-center transform scale-110">
                        <div className="bg-sky-100 rounded-full p-4 inline-block mb-3">
                          <FaRegCheckCircle className="text-5xl" />
                        </div>
                        <p className="font-medium text-sky-800">
                          {t("imageUploadedSuccessfully")}
                        </p>
                      </div>
                    </div>
                  )}
                </div>

                {/* Progress Indicator */}
                {isLoading && (
                  <div className="my-5">
                    <div className="relative pt-1">
                      <div className="overflow-hidden h-3 mb-2 text-xs flex rounded-full bg-sky-100">
                        <div
                          className="shadow-none flex flex-col text-center whitespace-nowrap text-white justify-center bg-gradient-to-r from-amber-500 to-amber-600 transition-all duration-500 ease-in-out rounded-full"
                          style={{ width: `${progressPercent}%` }}
                        ></div>
                      </div>
                      <div className="text-center">
                        <span className="text-xs font-medium text-amber-600">
                          {analysisStage === 1 && t("processingImage")}
                          {analysisStage === 2 && t("analyzingPlantHealth")}
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Left Column - Image Preview */}
                <div className="lg:col-span-1">
                  <div className="bg-white p-6 rounded-lg shadow-sm border border-amber-100">
                    <h3 className="text-lg font-semibold mb-4 flex items-center">
                      <FaCamera className="mr-2 text-amber-500" />
                      {t("plantImage")}
                    </h3>
                    <img
                      src={previewUrl}
                      alt="Analyzed plant"
                      className="w-full rounded-lg border border-amber-100"
                    />
                    <button
                      onClick={handleClear}
                      className="w-full mt-4 px-4 py-2 bg-amber-100 hover:bg-amber-200 text-amber-800 rounded-lg transition-colors"
                    >
                      {t("analyzeAnother")}
                    </button>
                  </div>
                </div>

                {/* Right Column - Results */}
                <div className="lg:col-span-2">
                  <div className="bg-white p-6 rounded-lg shadow-sm border border-amber-100">
                    <h3 className="text-lg font-semibold mb-4 flex items-center">
                      <MdOutlineHealthAndSafety className="mr-2 text-sky-600" />
                      {t("analysisResults")}
                    </h3>
                    <div className="bg-sky-50 p-4 rounded-lg border border-sky-100">
                      <pre className="whitespace-pre-wrap text-gray-700">
                        {analysisResult}
                      </pre>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Error Display */}
            {error && (
              <div className="mt-6">
                <div className="bg-red-50 border-l-4 border-red-500 p-4 rounded-r-lg shadow-md">
                  <div className="flex items-center">
                    <FaTimes className="text-red-500 mr-3 text-xl" />
                    <div>
                      <h3 className="text-sm font-medium text-red-800">
                        {t("errorLabel")}
                      </h3>
                      <p className="mt-1 text-sm text-red-700">{error}</p>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </motion.div>
        </FadeInSection>
      </div>
    </div>
  );
}

export default DiseaseDetector;

