"use client";
import React, {
  useState,
  useEffect,
  useCallback,
  useRef,
  useMemo,
} from "react";
import { useLanguage } from "../../context/LanguageContext";
// Assuming predictYieldApi is correctly imported from your services
import { predictYieldApi } from "../../services/api";
import {
  FaLeaf, // Included for background
  FaSpinner,
  FaChartLine,
  FaMapMarkerAlt,
  FaRuler,
  FaCloudSun,
  FaSeedling,
  FaRegCheckCircle,
  FaTimes,
  FaSearchLocation,
  FaInfoCircle,
} from "react-icons/fa";
import { GiFarmTractor, GiWheat } from "react-icons/gi";
import { WiHumidity } from "react-icons/wi";
import { MdOutlineScience, MdOutlineWaterDrop } from "react-icons/md";
import LocationMapPicker from "../../components/LocationMapPicker";

// States supported by the backend's yield model (must match STATE_COEFFICIENTS keys exactly)
const INDIAN_STATES = [
  "Maharashtra", "Karnataka", "Gujarat", "Madhya Pradesh", "Punjab",
  "Haryana", "Uttar Pradesh", "Bihar", "West Bengal", "Tamil Nadu",
  "Andhra Pradesh", "Telangana",
];

// Mirrors the backend's season-window logic in yield_service.py
const getCurrentSeason = () => {
  const month = new Date().getMonth() + 1;
  if (month >= 6 && month <= 10) return "Kharif";
  if (month === 11 || month === 12 || month <= 2) return "Rabi";
  return "Summer"; // Mar - May
};

// Matches a free-text state name (e.g. from OSM reverse geocoding) to the backend's expected value
const matchStateName = (osmState) => {
  if (!osmState) return null;
  return INDIAN_STATES.find((s) => s.toLowerCase() === osmState.toLowerCase()) || null;
};

// Fade in animation component (remains the same)
const FadeInSection = ({ children, delay = 0 }) => {
  const [isVisible, setVisible] = useState(false);
  const domRef = useRef(); // Use useRef directly

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
      if (currentRef) {
        // observer.unobserve(currentRef); // Optional
      }
      observer.disconnect();
    };
  }, []);

  return (
    <div
      ref={domRef}
      className={`transition-all duration-700 ease-out ${
        isVisible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-5" // Adjusted transform
      }`}
      style={{
        transitionDelay: `${delay}ms`,
      }}
    >
      {children}
    </div>
  );
};

// Tooltip component (remains the same)
const Tooltip = ({ content }) => {
  const [showTooltip, setShowTooltip] = useState(false);

  return (
    <div className="relative inline-block ml-2">
      <button
        type="button" // Add type="button" to prevent form submission
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        className="text-gray-400 hover:text-gray-600 focus:outline-none"
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

function YieldPredictor() {
  const { t } = useLanguage();
  // Form state (remains the same)
  const [formData, setFormData] = useState({
    crop: "",
    area: "",
    area_unit: "hectares",
    season: getCurrentSeason(),
    state: "",
    annual_rainfall: "",
    fertilizer: "",
    pesticide: "",
    ph: "6.5",
    n: "140",
    p: "50",
    k: "200",
    organic_carbon: "0.5",
    latitude: "",
    longitude: "",
    location_name: "",
  });

  // UI state (remains the same)
  const [showMap, setShowMap] = useState(false);
  const [locationSelected, setLocationSelected] = useState(false);
  const [autoLocationEnabled, setAutoLocationEnabled] = useState(false);
  const [gettingLocation, setGettingLocation] = useState(false);
  const [gettingWeather, setGettingWeather] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [prediction, setPrediction] = useState(null);
  const [analysisStage, setAnalysisStage] = useState(0);
  const [progressPercent, setProgressPercent] = useState(0);
  const [formSubmitted, setFormSubmitted] = useState(false);
  const [weatherData, setWeatherData] = useState(null);
  const [locationWeather, setLocationWeather] = useState(null);
  const [activeTab, setActiveTab] = useState("form");
  const isLoadingRef = useRef(isLoading); // Add ref for async checks

  // Available options (remains the same)
  const crops = [
    "Rice",
    "Jowar",
    "Bajra",
    "Maize",
    "Ragi",
    "Wheat",
    "Gram",
    "Tur",
    "Other Pulses",
    "Groundnut",
    "Sunflower",
    "Soyabean",
    "Safflower",
    "Nigerseed",
    "Other Oilseeds",
    "Cotton",
    "Sugarcane",
    "Tobacco",
    "Potato",
    "Onion",
    "Other Vegetables",
    "Fruits",
    "Total Foodgrains",
  ];

  // Progress animation effect (remains the same)
  useEffect(() => {
    let interval;
    if (isLoading) {
      if (analysisStage === 1) {
        setProgressPercent(0);
        interval = setInterval(
          () => setProgressPercent((prev) => Math.min(prev + 1, 45)),
          30
        );
      } else if (analysisStage === 2) {
        interval = setInterval(
          () => setProgressPercent((prev) => Math.min(prev + 1, 90)),
          40
        );
      }
    } else {
      setProgressPercent(0);
    }
    return () => clearInterval(interval);
  }, [isLoading, analysisStage]);

  // isLoading ref sync (remains the same)
  useEffect(() => {
    isLoadingRef.current = isLoading;
  }, [isLoading]);

  // Handle form input changes (remains the same)
  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData({ ...formData, [name]: value });
  };

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

  const fetchWeatherData = useCallback(async (lat, lng) => {
    setGettingWeather(true);
    try {
      const response = await fetch(
        `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lng}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,precipitation&timezone=auto`
      );
      const data = await response.json();
      if (data.current) {
        setLocationWeather({
          temperature: data.current.temperature_2m,
          humidity: data.current.relative_humidity_2m,
          windSpeed: data.current.wind_speed_10m,
          precipitation: data.current.precipitation,
          weatherCode: data.current.weather_code,
          timezone: data.timezone,
        });
      }
    } catch (err) {
      console.error("Failed to fetch weather:", err);
    } finally {
      setGettingWeather(false);
    }
  }, []);

  // Trailing 12-month rainfall total (mm) for the given coordinates, used as annual_rainfall
  const fetchAnnualRainfall = useCallback(async (lat, lng) => {
    try {
      const end = new Date();
      const start = new Date();
      start.setFullYear(end.getFullYear() - 1);
      const fmt = (d) => d.toISOString().split("T")[0];
      const response = await fetch(
        `https://archive-api.open-meteo.com/v1/archive?latitude=${lat}&longitude=${lng}&start_date=${fmt(start)}&end_date=${fmt(end)}&daily=precipitation_sum&timezone=auto`
      );
      const data = await response.json();
      if (data.daily?.precipitation_sum) {
        const total = data.daily.precipitation_sum.reduce(
          (sum, v) => sum + (v || 0),
          0
        );
        return Math.round(total);
      }
    } catch (err) {
      console.error("Failed to fetch annual rainfall:", err);
    }
    return null;
  }, []);

  const detectStateFromCoords = useCallback(async (lat, lng) => {
    try {
      const response = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lng}`
      );
      const data = await response.json();
      return matchStateName(data?.address?.state);
    } catch (err) {
      console.error("Failed to detect state:", err);
      return null;
    }
  }, []);

  // Fills in state, season, and annual_rainfall once a location is known.
  // addressData is reused if the caller already has an OSM reverse-geocode response.
  const applyLocationDerivedFields = useCallback(
    async (lat, lng, addressData) => {
      const detectedState =
        matchStateName(addressData?.address?.state) ||
        (await detectStateFromCoords(lat, lng));
      const annualRainfall = await fetchAnnualRainfall(lat, lng);

      setFormData((prev) => ({
        ...prev,
        state: detectedState || prev.state,
        season: prev.season || getCurrentSeason(),
        annual_rainfall:
          annualRainfall !== null ? annualRainfall : prev.annual_rainfall,
      }));
    },
    [detectStateFromCoords, fetchAnnualRainfall]
  );

  const handleLocationSelection = useCallback(
    (lat, lng, displayName, addressData = null) => {
      setFormData((prev) => ({
        ...prev,
        latitude: lat,
        longitude: lng,
        location_name: displayName || `${lat.toFixed(4)}, ${lng.toFixed(4)}`,
      }));
      setLocationSelected(true);
      applyLocationDerivedFields(lat, lng, addressData);
    },
    [applyLocationDerivedFields]
  );

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
          handleLocationSelection(latitude, longitude, locationName, data);
          await fetchWeatherData(latitude, longitude);
          setAutoLocationEnabled(true);
          setError("");
        } catch (err) {
          const fallbackLocationName = formatLocationLabel(null, latitude, longitude);
          handleLocationSelection(latitude, longitude, fallbackLocationName);
          await fetchWeatherData(latitude, longitude);
          setAutoLocationEnabled(true);
          setError("");
        } finally {
          setGettingLocation(false);
        }
      },
      (error) => {
        setError(`Location access denied: ${error.message}`);
        setGettingLocation(false);
      }
    );
  }, [fetchWeatherData, formatLocationLabel, handleLocationSelection]);

  // Handle form submission (remains the same)
  const handleSubmit = useCallback(
    async (e) => {
      e.preventDefault();
      setIsLoading(true);
      setPrediction(null);
      setError("");
      setFormSubmitted(true);
      setActiveTab("results"); // Switch to results tab on submit
      setAnalysisStage(1);
      setProgressPercent(0); // Reset progress

      // Simulate processing time
      await new Promise((resolve) => setTimeout(resolve, 1500));
      if (!isLoadingRef.current) return; // Check if still loading

      setAnalysisStage(2); // Move to analyzing stage

      try {
        // Convert relevant fields to numbers
        const numericData = {
          ...formData,
          area: Number.parseFloat(formData.area) || 0,
          annual_rainfall: Number.parseFloat(formData.annual_rainfall) || 0,
          fertilizer: Number.parseFloat(formData.fertilizer) || 0,
          pesticide: Number.parseFloat(formData.pesticide) || 0,
          ph: Number.parseFloat(formData.ph) || 0,
          n: Number.parseFloat(formData.n) || 0,
          p: Number.parseFloat(formData.p) || 0,
          k: Number.parseFloat(formData.k) || 0,
          organic_carbon: Number.parseFloat(formData.organic_carbon) || 0,
        };
        // Include location data if available
        if (formData.latitude && formData.longitude) {
          numericData.latitude = Number.parseFloat(formData.latitude);
          numericData.longitude = Number.parseFloat(formData.longitude);
          numericData.location_name = formData.location_name; // Keep string name
        }

        // ---- API Call ----
        const result = await predictYieldApi(numericData);
        // ---- End API Call ----

        if (!isLoadingRef.current) return; // Check if still loading

        // Simulate final analysis time
        await new Promise((resolve) => setTimeout(resolve, 1000));
        if (!isLoadingRef.current) return;

        setPrediction(result); // Set prediction state
        setAnalysisStage(3); // Set stage to complete
        setProgressPercent(100); // Set progress to 100%

        if (result.weather_data) {
          setWeatherData(result.weather_data); // Store weather data if returned
        }
      } catch (err) {
        console.error("Yield Prediction Error:", err); // Log the error
        const errorMsg =
          err.response?.data?.error ||
          err.message ||
          "Failed to predict yield. Please check inputs and try again.";
        setError(errorMsg);
        setAnalysisStage(0); // Reset stage on error
        setProgressPercent(0); // Reset progress
      } finally {
        // Short delay before setting loading false to show 100% complete
        setTimeout(() => {
          if (isLoadingRef.current) {
            // Check ref again before setting state
            setIsLoading(false);
          }
        }, 500);
      }
    },
    [formData]
  ); // Dependency: formData

  // Reset form (remains the same)
  const handleReset = useCallback(() => {
    setFormData({
      crop: "",
      area: "",
      area_unit: "hectares",
      season: getCurrentSeason(),
      state: "",
      annual_rainfall: "",
      fertilizer: "",
      pesticide: "",
      ph: "6.5",
      n: "140",
      p: "50",
      k: "200",
      organic_carbon: "0.5",
      latitude: "",
      longitude: "",
      location_name: "",
    });
    setPrediction(null);
    setError("");
    setIsLoading(false);
    setAnalysisStage(0);
    setProgressPercent(0);
    setFormSubmitted(false);
    setShowMap(false);
    setLocationSelected(false);
    setAutoLocationEnabled(false);
    setLocationWeather(null);
    setActiveTab("form");
  }, []);

  // Calculate yield potential (remains the same, purely illustrative)
  const calculateYieldPotential = useMemo(() => {
    /* ... unchanged ... */
  }, [formData]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-50 via-sky-50 to-cyan-50 pt-24 pb-12 flex flex-col items-center justify-center px-4">
      {" "}
      {/* Added px-4 for padding */}
      {/* Subtle background elements */}
      <div className="absolute top-0 left-0 w-full h-full overflow-hidden pointer-events-none z-0">
        {/* Subtle wheat accents (Existing) */}
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

        {/* ADJUSTED Subtle leaf accents - positioned to avoid direct overlap */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          {/* Leaf - Top Left Corner */}
          <FaLeaf
            className="absolute text-green-400 text-4xl" // Green color for leaves
            style={{
              left: "5%", // Moved further left
              top: "8%", // Moved slightly up
              opacity: 0.1, // Slightly less opaque
              transform: "rotate(-30deg) scale(2.0)", // Adjusted rotation/scale
            }}
          />

          {/* Leaf - Middle Left */}
          <FaLeaf
            className="absolute text-green-400 text-4xl"
            style={{
              left: "15%", // Shifted position
              bottom: "45%", // Mid-bottom area
              opacity: 0.09,
              transform: "rotate(75deg) scale(1.8)",
            }}
          />

          {/* Leaf - Bottom Center-Right */}
          <FaLeaf
            className="absolute text-green-400 text-4xl"
            style={{
              right: "35%", // Towards center bottom right
              bottom: "5%",
              opacity: 0.08,
              transform: "rotate(-15deg) scale(2.2)",
            }}
          />

          {/* Leaf - Top Center-Right */}
          <FaLeaf
            className="absolute text-green-400 text-4xl"
            style={{
              right: "20%", // Shifted
              top: "8%", // Near top but different spot
              opacity: 0.07,
              transform: "rotate(55deg) scale(1.6)",
            }}
          />

          {/* Leaf - Far Bottom Right Corner */}
          <FaLeaf
            className="absolute text-green-400 text-4xl"
            style={{
              right: "5%", // Far corner
              bottom: "8%", // Far corner
              opacity: 0.11,
              transform: "rotate(25deg) scale(2.1)",
            }}
          />
        </div>
      </div>
      {/* Page Header (remains the same) */}
      <div className="text-center mb-10 w-full relative z-10">
        <FadeInSection>
          {" "}
          {/* Wrap header */}
          <div className="inline-flex p-4 bg-gradient-to-r from-amber-100 to-sky-100 rounded-full text-amber-800 mb-5 shadow-md">
            <GiWheat className="text-4xl" />
          </div>
          <h1 className="text-3xl md:text-4xl font-extrabold mb-3 text-amber-900 bg-clip-text text-transparent bg-gradient-to-r from-amber-700 to-sky-700">
            Crop Yield Predictor
          </h1>
          <p className="text-gray-600 max-w-xl md:max-w-2xl mx-auto text-sm md:text-base">
            Optimize your harvest with AI-powered yield predictions and
            personalized farming recommendations.
          </p>
        </FadeInSection>
      </div>
      {/* Main Content */}
      <div className="w-full max-w-7xl relative z-10 transition-all duration-500">
        {/* Main container */}
        <div className="bg-white rounded-xl shadow-lg p-6 md:p-8 border border-amber-100 transform transition-all duration-300 hover:shadow-xl relative overflow-hidden">
          {/* Subtle background pattern (remains) */}
          <div className="absolute top-0 left-0 w-full h-full opacity-5 pointer-events-none">
            {/* SVG pattern */}
            <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
              <pattern
                id="pattern-yield"
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
                fill="url(#pattern-yield)"
              />
            </svg>
          </div>
          {/* Grid Layout for Form and Results */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 relative z-10">
            {/* Form Section (Left/Main Column) */}
            <div
              className={`lg:col-span-2 transition-opacity duration-500 ${
                activeTab !== "form"
                  ? "opacity-0 lg:opacity-100 pointer-events-none lg:pointer-events-auto"
                  : "opacity-100"
              }`}
            >
              <FadeInSection delay={100}>
                {" "}
                {/* Fade in form section */}
                {/* Form Card */}
                <div className="bg-white p-6 rounded-lg shadow-sm border border-amber-100 transition-all duration-300 hover:shadow-md">
                  {/* Form Header */}
                  <div className="flex items-center justify-between mb-6 border-b pb-4 border-gray-100">
                    <h3 className="text-xl font-semibold text-gray-800 flex items-center">
                      <FaSeedling className="mr-2 text-sky-500" />
                      {t("enterCropDetails")}
                    </h3>
                    <div className="flex space-x-2">
                      <button
                        type="button"
                        onClick={handleReset}
                        className="px-3 py-1 text-xs md:text-sm border border-gray-300 rounded-md text-gray-600 hover:bg-gray-50 transition-colors transform hover:-translate-y-0.5 hover:shadow-sm duration-300"
                      >
                        {t("resetForm")}
                      </button>
                      {/* Conditionally render View Results button */}
                      {prediction && (
                        <button
                          type="button"
                          onClick={() => setActiveTab("results")}
                          disabled={!prediction}
                          className="px-3 py-1 text-xs md:text-sm rounded-md transition-all duration-300 transform hover:-translate-y-0.5 hover:shadow-sm bg-amber-500 text-white hover:bg-amber-600"
                        >
                          View Results
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Form Fields */}
                  <form onSubmit={handleSubmit} className="space-y-6">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="form-group">
                        <label className="block text-sm font-medium text-gray-700 mb-1 flex items-center">
                          <FaLeaf className="mr-1.5 text-sky-500 text-base" />{" "}
                          Crop Type <span className="text-red-500 ml-1">*</span>
                          <Tooltip content="Select the primary crop" />
                        </label>
                        <select
                          name="crop"
                          value={formData.crop}
                          onChange={handleChange}
                          className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-amber-500 bg-white transition-all duration-300 hover:border-amber-300 text-sm"
                          required
                        >
                          <option value="">{t("selectACrop")}</option>
                          {crops.map((crop) => (
                            <option key={crop} value={crop}>
                              {crop}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="form-group">
                        <label className="block text-sm font-medium text-gray-700 mb-1 flex items-center">
                          <FaRuler className="mr-1.5 text-gray-600 text-base" />{" "}
                          {t("area")} <span className="text-red-500 ml-1">*</span>
                        </label>
                        <div className="flex gap-2">
                          <input
                            type="number"
                            name="area"
                            value={formData.area}
                            onChange={handleChange}
                            placeholder={t("areaPlaceholder")}
                            className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-amber-500 transition-all duration-300 hover:border-amber-300 text-sm"
                            min="0.01"
                            step="0.01"
                            required
                          />
                          <select
                            name="area_unit"
                            value={formData.area_unit || "hectares"}
                            onChange={(e) => setFormData((prev) => ({ ...prev, area_unit: e.target.value }))}
                            className="p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-amber-500 bg-white text-sm"
                          >
                            <option value="hectares">{t("hectares")}</option>
                            <option value="acres">{t("acres")}</option>
                          </select>
                        </div>
                      </div>
                    </div>

                    <div className="form-group border-t pt-4 mt-4 border-gray-100">
                      <label className="block text-sm font-medium text-gray-700 mb-2 flex items-center">
                        <FaMapMarkerAlt className="mr-1.5 text-red-500 text-base" />{" "}
                        {t("farmLocation")}
                        <Tooltip content={t("locationAccuracyTooltip") || "Precise location improves weather accuracy"} />
                      </label>
                      <div className="flex flex-wrap items-center gap-3 mb-3">
                        <input
                          type="checkbox"
                          id="yield-auto-location"
                          checked={autoLocationEnabled}
                          onChange={(e) => {
                            if (e.target.checked) {
                              handleAutoLocation();
                            } else {
                              setAutoLocationEnabled(false);
                              setLocationWeather(null);
                            }
                          }}
                          disabled={gettingLocation || gettingWeather}
                          className="h-4 w-4 rounded border-gray-300"
                        />
                        <label htmlFor="yield-auto-location" className="text-sm text-gray-700 cursor-pointer">
                          {t("enableAutoLocation")}
                        </label>
                        {(gettingLocation || gettingWeather) && (
                          <FaSpinner className="animate-spin text-amber-600 text-sm" />
                        )}
                      </div>
                      <div className="flex items-center space-x-3 mb-3">
                        <button
                          type="button"
                          onClick={() => setShowMap(!showMap)}
                          className="flex items-center px-4 py-2 bg-blue-100 text-blue-700 text-sm rounded-lg hover:bg-blue-200 transition-colors shadow-sm"
                        >
                          <FaSearchLocation className="mr-2" />{" "}
                          {showMap ? t("hideMap") : t("selectOnMap")}
                        </button>
                        {locationSelected && (
                          <span className="text-xs text-sky-600 flex items-center">
                            <FaRegCheckCircle className="mr-1" /> {t("locationSet")}
                          </span>
                        )}
                      </div>
                      {locationSelected && formData.location_name && (
                        <div className="mb-3 flex items-start gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800">
                          <FaMapMarkerAlt className="mt-0.5 text-sky-600 flex-shrink-0" />
                          <div>
                            <div className="font-medium">{t("selectedLocation")}</div>
                            <div className="text-sky-700">{formData.location_name}</div>
                          </div>
                        </div>
                      )}
                      {showMap && (
                        <FadeInSection>
                          <div className="mt-2 space-y-3 p-4 bg-gray-50 rounded-lg border">
                            <LocationMapPicker
                              latitude={Number.parseFloat(formData.latitude) || null}
                              longitude={Number.parseFloat(formData.longitude) || null}
                              location={formData.location_name}
                              onLocationChange={(value) =>
                                setFormData((prev) => ({ ...prev, location_name: value }))
                              }
                              onCoordinatesChange={handleLocationSelection}
                              onWeatherRefresh={fetchWeatherData}
                            />
                          </div>
                        </FadeInSection>
                      )}
                      {locationWeather && (
                        <div className="mt-3 p-3 bg-blue-50 rounded border border-blue-200 text-sm space-y-1">
                          <div className="text-blue-900 font-medium flex items-center">
                            <FaCloudSun className="mr-2" /> {t("currentConditions")}
                          </div>
                          <div className="text-blue-700">🌡️ Temperature: <span className="font-medium">{locationWeather.temperature}°C</span></div>
                          <div className="text-blue-700">💧 Humidity: <span className="font-medium">{locationWeather.humidity}%</span></div>
                          <div className="text-blue-700">💨 Wind Speed: <span className="font-medium">{locationWeather.windSpeed} km/h</span></div>
                          <div className="text-blue-700">🌧️ Precipitation: <span className="font-medium">{locationWeather.precipitation} mm</span></div>
                        </div>
                      )}
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
                        <div className="form-group">
                          <label className="block text-xs font-medium text-gray-700 mb-1">
                            State <span className="text-red-500">*</span>
                          </label>
                          <select
                            name="state"
                            value={formData.state}
                            onChange={handleChange}
                            className="w-full p-2.5 border border-gray-300 rounded-lg focus:ring-1 focus:ring-amber-500 focus:border-amber-500 bg-white text-sm"
                            required
                          >
                            <option value="">Select state</option>
                            {INDIAN_STATES.map((s) => (
                              <option key={s} value={s}>
                                {s}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div className="form-group">
                          <label className="block text-xs font-medium text-gray-700 mb-1">
                            Season <span className="text-red-500">*</span>
                          </label>
                          <select
                            name="season"
                            value={formData.season}
                            onChange={handleChange}
                            className="w-full p-2.5 border border-gray-300 rounded-lg focus:ring-1 focus:ring-amber-500 focus:border-amber-500 bg-white text-sm"
                            required
                          >
                            <option value="Kharif">Kharif</option>
                            <option value="Rabi">Rabi</option>
                            <option value="Summer">Summer</option>
                          </select>
                        </div>
                        <div className="form-group">
                          <label className="block text-xs font-medium text-gray-700 mb-1">
                            Annual Rainfall (mm) <span className="text-red-500">*</span>
                          </label>
                          <input
                            type="number"
                            name="annual_rainfall"
                            value={formData.annual_rainfall}
                            onChange={handleChange}
                            placeholder="Auto-filled from location"
                            className="w-full p-2.5 border border-gray-300 rounded-lg focus:ring-1 focus:ring-amber-500 focus:border-amber-500 text-sm"
                            min="0"
                            required
                          />
                        </div>
                      </div>
                    </div>

                    {/* Soil Health Section */}
                    <div className="bg-gradient-to-r from-amber-50 to-sky-50/30 p-5 rounded-lg border border-amber-200/50 transition-all duration-300 hover:shadow-md">
                      <h4 className="text-md font-medium mb-4 flex items-center text-gray-800">
                        <MdOutlineScience className="mr-2 text-amber-600" />{" "}
                        {t("soilHealthParameters")}{" "}
                        <span className="text-red-500 ml-1">*</span>
                      </h4>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        {/* pH */}
                        <div className="form-group">
                          <label className="block text-xs font-medium text-gray-700 mb-1">
                            {t("soilPH")}
                          </label>
                          <input
                            type="number"
                            name="ph"
                            value={formData.ph}
                            onChange={handleChange}
                            placeholder="e.g., 6.5"
                            className="w-full p-2.5 border border-gray-300 rounded-lg focus:ring-1 focus:ring-amber-500 focus:border-amber-500 text-sm"
                            min="0"
                            max="14"
                            step="0.1"
                            required
                          />
                        </div>
                        {/* N */}
                        <div className="form-group">
                          <label className="block text-xs font-medium text-gray-700 mb-1">
                            {t("nLabel")}
                          </label>
                          <input
                            type="number"
                            name="n"
                            value={formData.n}
                            onChange={handleChange}
                            placeholder="e.g., 140"
                            className="w-full p-2.5 border border-gray-300 rounded-lg focus:ring-1 focus:ring-amber-500 focus:border-amber-500 text-sm"
                            min="0"
                            required
                          />
                        </div>
                        {/* P */}
                        <div className="form-group">
                          <label className="block text-xs font-medium text-gray-700 mb-1">
                            {t("pLabel")}
                          </label>
                          <input
                            type="number"
                            name="p"
                            value={formData.p}
                            onChange={handleChange}
                            placeholder="e.g., 50"
                            className="w-full p-2.5 border border-gray-300 rounded-lg focus:ring-1 focus:ring-amber-500 focus:border-amber-500 text-sm"
                            min="0"
                            required
                          />
                        </div>
                        {/* K */}
                        <div className="form-group">
                          <label className="block text-xs font-medium text-gray-700 mb-1">
                            {t("kLabel")}
                          </label>
                          <input
                            type="number"
                            name="k"
                            value={formData.k}
                            onChange={handleChange}
                            placeholder="e.g., 200"
                            className="w-full p-2.5 border border-gray-300 rounded-lg focus:ring-1 focus:ring-amber-500 focus:border-amber-500 text-sm"
                            min="0"
                            required
                          />
                        </div>
                        {/* Organic Carbon */}
                        <div className="form-group md:col-span-2">
                          <label className="block text-xs font-medium text-gray-700 mb-1">
                            {t("organicCarbonLabel")}
                          </label>
                          <input
                            type="number"
                            name="organic_carbon"
                            value={formData.organic_carbon}
                            onChange={handleChange}
                            placeholder="e.g., 0.5"
                            className="w-full p-2.5 border border-gray-300 rounded-lg focus:ring-1 focus:ring-amber-500 focus:border-amber-500 text-sm"
                            min="0"
                            max="10"
                            step="0.01"
                            required
                          />
                        </div>
                      </div>
                    </div>

                    {/* Farm Management Section */}
                    <div className="bg-gradient-to-r from-sky-50/30 to-amber-50 p-5 rounded-lg border border-sky-100/50 transition-all duration-300 hover:shadow-md">
                      <h4 className="text-md font-medium mb-4 flex items-center text-gray-800">
                        <GiFarmTractor className="mr-2 text-sky-600" /> {t("farmManagement")} <span className="text-red-500 ml-1">*</span>
                      </h4>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="form-group">
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            {t("fertilizerLabel")}
                          </label>
                          <input
                            type="number"
                            name="fertilizer"
                            value={formData.fertilizer}
                            onChange={handleChange}
                            placeholder="e.g., 100"
                            className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-amber-500 text-sm"
                            min="0"
                            required
                          />
                        </div>
                        <div className="form-group">
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            {t("pesticideLabel")}
                          </label>
                          <input
                            type="number"
                            name="pesticide"
                            value={formData.pesticide}
                            onChange={handleChange}
                            placeholder="e.g., 2"
                            className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-amber-500 text-sm"
                            min="0"
                            step="0.01"
                            required
                          />
                        </div>
                      </div>
                    </div>

                    {/* Submit Button */}
                    <div className="pt-4">
                      <button
                        type="submit"
                        disabled={isLoading}
                        className="w-full bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-600 hover:to-amber-700 text-white py-3 px-6 rounded-lg font-semibold text-base flex items-center justify-center transition-all duration-300 shadow-md hover:shadow-lg transform hover:-translate-y-0.5 disabled:opacity-60 disabled:cursor-not-allowed"
                      >
                        {isLoading ? (
                          <>
                            <FaSpinner className="animate-spin mr-2" />{" "}
                            {t("predictingYield")}
                          </>
                        ) : (
                          <>
                            <FaChartLine className="mr-2" /> {t("predictYield")}
                          </>
                        )}
                      </button>
                    </div>
                  </form>
                </div>
              </FadeInSection>
            </div>
            {/* Results Section (Right Column) */}
            <div
              className={`lg:col-span-1 transition-opacity duration-500 ${
                activeTab !== "results"
                  ? "opacity-0 lg:opacity-100 pointer-events-none lg:pointer-events-auto"
                  : "opacity-100"
              }`}
            >
              <div className="sticky top-6">
                {" "}
                {/* Make results sticky */}
                {/* Loading State */}
                {isLoading && (
                  <FadeInSection>
                    <div className="bg-white p-6 rounded-lg shadow-md border border-gray-100 text-center">
                      <div className="relative w-16 h-16 mx-auto mb-4">
                        <div className="absolute inset-0 rounded-full border-4 border-amber-100 animate-pulse"></div>
                        <FaSpinner className="animate-spin text-3xl text-amber-500 absolute inset-0 m-auto" />
                      </div>
                      <h3 className="text-lg font-semibold mb-2 text-gray-700">
                        {analysisStage === 1
                          ? t("processingData")
                          : t("analyzingConditions")}
                      </h3>
                      <div className="w-full bg-gray-200 rounded-full h-2 mb-4 overflow-hidden">
                        <div
                          className="bg-gradient-to-r from-amber-400 to-amber-600 h-2 rounded-full transition-all duration-300"
                          style={{ width: `${progressPercent}%` }}
                        ></div>
                      </div>
                      <p className="text-sm text-gray-500">
                        {analysisStage === 1
                          ? t("preparingInputs")
                          : t("calculatingPrediction")}
                      </p>
                    </div>
                  </FadeInSection>
                )}
                {/* Error State */}
                {error && !isLoading && (
                  <FadeInSection>
                    <div className="bg-red-50 border-l-4 border-red-500 p-4 rounded-r-lg shadow-md">
                      <div className="flex items-center">
                        <FaTimes className="text-red-500 mr-3 text-xl" />
                        <div>
                          <h3 className="text-sm font-medium text-red-800">
                            {t("predictionError")}
                          </h3>
                          <p className="mt-1 text-sm text-red-700">{error}</p>
                          <button
                            onClick={() => {
                              setError("");
                              setActiveTab("form");
                            }}
                            className="mt-2 text-sm text-red-600 hover:underline"
                          >
                            Edit Inputs & Try Again
                          </button>
                        </div>
                      </div>
                    </div>
                  </FadeInSection>
                )}
                {/* Initial Placeholder State */}
                {!isLoading && !error && !prediction && !formSubmitted && (
                  <FadeInSection delay={200}>
                    <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-100 text-center">
                      <div className="bg-amber-100 p-4 rounded-full inline-block mb-4">
                        <GiWheat className="text-3xl text-amber-600" />
                      </div>
                      <h3 className="text-lg font-semibold mb-2 text-gray-700">
                        {t("yieldPredictionAwaits")}
                      </h3>
                      <p className="text-sm text-gray-500 mb-5">
                        {t("fillFormForEstimates")}
                      </p>
                      {/* You can add illustrative icons/text here */}
                    </div>
                  </FadeInSection>
                )}
                {/* Success/Results State */}
                {!isLoading && prediction && (
                  <FadeInSection delay={100}>
                    <div className="bg-white rounded-lg shadow-md border border-amber-100 overflow-hidden">
                      {/* Results Header */}
                      <div className="bg-gradient-to-r from-sky-600 to-sky-700 p-5 text-white">
                        <div className="flex items-center">
                          <FaRegCheckCircle className="text-xl mr-2.5" />
                          <h3 className="text-lg font-semibold">
                            {t("predictionResults")}
                          </h3>
                        </div>
                        <p className="text-green-100 text-xs mt-1">
                          {t("analysisFor")} {formData.crop} in {formData.location_name || t("selectedLocation")}
                        </p>
                      </div>

                      {/* Results Content */}
                      <div className="p-5 space-y-5">
                        {/* Key Metrics */}
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                          <div className="bg-sky-50 p-4 rounded-lg border border-sky-100/50 text-center">
                            <p className="text-xs text-sky-700 font-medium mb-1 uppercase tracking-wider">
                              Predicted Yield
                            </p>
                            <p className="text-2xl font-bold text-sky-800">
                              {prediction.yield.toFixed(2)}{" "}
                              <span className="text-sm font-normal">t/ha</span>
                            </p>
                          </div>
                          <div className="bg-amber-50 p-4 rounded-lg border border-amber-100/50 text-center">
                            <p className="text-xs text-amber-700 font-medium mb-1 uppercase tracking-wider">
                              Est. Production
                            </p>
                            <p className="text-2xl font-bold text-amber-800">
                              {prediction.estimated_production.toFixed(2)}{" "}
                              <span className="text-sm font-normal">tons</span>
                            </p>
                          </div>
                        </div>

                        {/* Weather Data */}
                        {weatherData && (
                          <div className="border-t pt-4 mt-4 border-gray-100">
                            <h4 className="text-sm font-semibold text-gray-800 mb-3 flex items-center">
                              <FaCloudSun className="mr-2 text-blue-500" />{" "}
                              {t("currentConditions")}
                            </h4>
                            <div className="bg-blue-50 p-4 rounded-lg border border-blue-100/50">
                              <div className="grid grid-cols-2 gap-3 text-xs">
                                {/* Weather details */}
                                <div className="flex items-center">
                                  <span className="font-medium mr-1">
                                    {t("temperature")}
                                  </span>{" "}
                                  {weatherData.current_temp}°C
                                </div>
                                <div className="flex items-center">
                                  <span className="font-medium mr-1">
                                    {t("humidity")}
                                  </span>{" "}
                                  {weatherData.current_humidity}%
                                </div>
                                <div className="col-span-2 flex items-center">
                                  <span className="font-medium mr-1">
                                    {t("condition")}
                                  </span>{" "}
                                  <span className="capitalize">
                                    {weatherData.current_conditions?.toLowerCase()}
                                  </span>
                                </div>
                                <div className="col-span-2 flex items-center">
                                  <span className="font-medium mr-1">
                                    {t("estimatedRainfallMonth")}
                                  </span>{" "}
                                  {weatherData.monthly_rainfall_estimate?.toFixed(
                                    1
                                  )}{" "}
                                  cm
                                </div>
                              </div>
                            </div>
                          </div>
                        )}

                        {/* Recommendations */}
                        <div className="border-t pt-4 mt-4 border-gray-100">
                          <h4 className="text-sm font-semibold text-gray-800 mb-3 flex items-center">
                            <FaSeedling className="mr-2 text-sky-600" />{" "}
                            {t("recommendationsLabel")}
                          </h4>
                          <ul className="space-y-2">
                            {prediction.recommendations?.map((rec, index) => (
                              <li
                                key={index}
                                className="flex items-start text-xs text-gray-700"
                              >
                                <FaRegCheckCircle className="text-sky-500 mr-2 mt-0.5 flex-shrink-0" />
                                <span>{rec}</span>
                              </li>
                            ))}
                          </ul>
                        </div>

                        {/* Buttons and Disclaimer */}
                        <div className="border-t pt-4 mt-4 border-gray-100 space-y-3">
                          <button
                            onClick={() => setActiveTab("form")}
                            className="w-full text-center text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 py-2 px-4 rounded-lg transition-colors"
                          >
                            {t("adjustParametersPredictAgain")}
                          </button>
                          <p className="text-xs text-gray-400 text-center italic">
                            {t("predictionsEstimateDisclaimer")}
                          </p>
                        </div>
                      </div>
                    </div>
                  </FadeInSection>
                )}
              </div>{" "}
              {/* End Sticky container */}
            </div>{" "}
            {/* End Results Column */}
          </div>{" "}
          {/* End Grid */}
        </div>{" "}
        {/* End Main Card */}
      </div>{" "}
      {/* End Max Width Container */}
      {/* Removed style jsx block */}
    </div> // End Root Container
  );
}

export default YieldPredictor;

