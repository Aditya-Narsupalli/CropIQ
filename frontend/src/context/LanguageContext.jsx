import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

const LanguageContext = createContext(null);

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
  { value: "ml", label: "മലയാളം (Malayalam)" },
];

const translations = {
  en: {
    language: "Language",
    home: "Home",
    market: "Market",
    disease: "Disease Detector",
    yield: "Yield Predictor",
    aiChat: "AI Chat",
    microfarm: "Micro Farm",
    login: "Login",
    share: "Share",
    typeMessage: "Type your message...",
    send: "Send",
    voiceInput: "Voice input",
    chatWelcome: "Welcome to CropIQ AI!",
    switchingLanguage: "Switching language",
    quickQuestions: "Quick Questions",
    chatDescription: "Get personalized agricultural advice.",
    modeActive: "mode is active",
    enableAutoLocation: "Enable auto location",
    hideMap: "Hide Map",
    selectOnMap: "Select on Map",
    selectedLocation: "Selected location",
    currentWeather: "Current Weather",
    temperature: "Temperature",
    humidity: "Humidity",
    windSpeed: "Wind Speed",
    marketPriceDashboard: "Market Price Dashboard",
    marketPriceDashboardDescription: "Track real-time crop prices.",
    currentMarketPrices: "Current Market Prices",
    filterByCropName: "Filter by crop name...",
    locationLabel: "Location",
    price: "Price",
    change: "Change",
    diseaseDetectorTitle: "Crop Disease Detector",
    diseaseDetectorDescription: "Upload an image of your plant to detect diseases.",
    cropType: "Crop Type",
    locationLabelAlt: "Location",
    uploadPlantImage: "Upload your plant image",
    dragDrop: "Drag & drop",
    browseFiles: "Browse files",
    clear: "Clear",
    analyzeImage: "Analyze Image",
    imageUploadedSuccessfully: "Image uploaded successfully!",
    processingImage: "Preprocessing image...",
    analyzingPlantHealth: "Analyzing plant health...",
    plantImage: "Plant Image",
    analyzeAnother: "Analyze Another",
    analysisResults: "Analysis Results",
    locationSet: "Location Set",
    microfarmPageTitle: "Micro Farm Maximizer",
    microfarmDescription: "Optimize your small plot with AI-powered farming recommendations.",
    enterFarmDetails: "Enter Farm Details",
    resetForm: "Reset Form",
    plotSize: "Plot Size",
    sqFt: "sq ft",
    acres: "acres",
    budgetLabelWithCurrency: "Budget (₹)",
    soilType: "Soil Type",
    soilPH: "Soil pH (if known)",
    waterSource: "Water Source",
    preferredCrops: "Preferred Crops",
    preferredCropsPlaceholder: "Tomatoes, Lettuce, etc.",
    laborAvailability: "Labor Availability (1-100)",
    getRecommendations: "Get Recommendations",
    farmSystemRecommendations: "Farm System Recommendations",
    setupCost: "Setup Cost:",
    monthlyCost: "Monthly Cost:",
    expectedROI: "Expected ROI:",
    paybackPeriod: "Payback Period:",
    waterUsage: "Water Usage:",
    electricityUsage: "Electricity Usage:",
    suitableCrops: "Suitable Crops:",
    recommendationsAwait: "Recommendations Await",
    yieldPredictorTitle: "Crop Yield Predictor",
    yieldPredictorDescription: "Optimize your harvest with AI-powered yield predictions.",
    enterCropDetails: "Enter Crop Details",
    selectACrop: "Select a crop",
    area: "Area",
    areaPlaceholder: "e.g., 2.5",
    farmLocation: "Farm Location",
    currentConditions: "Current Conditions",
    fertilizerLabel: "Fertilizer (kg/ha)",
    pesticideLabel: "Pesticide (kg/ha)",
    organicCarbonLabel: "Organic Carbon (%)",
    predictYield: "Predict Yield",
    predictingYield: "Predicting Yield...",
    processingData: "Processing Data...",
    analyzingConditions: "Analyzing Conditions...",
    predictionError: "Prediction Error",
    editInputsTryAgain: "Edit Inputs & Try Again",
    yieldPredictionAwaits: "Yield Prediction Awaits",
    fillFormForEstimates: "Fill the form to get AI-powered yield estimates and insights.",
    predictionResults: "Prediction Results",
    analysisFor: "Analysis for",
    predictedYield: "Predicted Yield",
    estimatedProduction: "Est. Production",
    recommendationsLabel: "Recommendations",
    adjustParametersPredictAgain: "Adjust Parameters & Predict Again",
    predictionsEstimateDisclaimer: "Note: Predictions are estimates based on provided data. Actual results may vary.",
    errorLabel: "Error",
    hectares: "Hectares",
    selectCropTooltip: "Select the primary crop",
    estimatedRainfallMonth: "Est. Rainfall (Month):",
  },
  hi: {
    enableAutoLocation: "स्वचालित स्थान सक्षम करें",
    selectedLocation: "चयनित स्थान",
    currentWeather: "वर्तमान मौसम",
    temperature: "तापमान",
    humidity: "आर्द्रता",
    windSpeed: "हवा की रफ्तार",
    language: "भाषा",
    home: "होम",
    market: "बाज़ार",
    disease: "रोग पहचान",
    yield: "उत्पादन पूर्वानुमान",
    aiChat: "एआई चैट",
    microfarm: "माइक्रो फार्म",
    processing: "प्रसंस्करण जारी है...",
    getRecommendations: "अनुसंधान पाएं",
    recommendationsAwait: "सिफारिशें प्रतीक्षारत",
    cropType: "फसल प्रकार",
    locationSet: "स्थान सेट",
    siteWeather: "मौसम",
    errorLabel: "त्रुटि",
  },
};

const fallbackTranslations = translations.en;

export function LanguageProvider({ children }) {
  const [language, setLanguage] = useState(() => {
    if (typeof window === "undefined") return "en";
    return window.localStorage.getItem("cropiq-language") || "en";
  });

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem("cropiq-language", language);
    }
  }, [language]);

  const t = (key, params = {}) => {
    const currentLanguageTranslations = translations[language] || fallbackTranslations;
    const rawValue = currentLanguageTranslations[key] || fallbackTranslations[key] || key;

    return rawValue.replace(/\{(\w+)\}/g, (_match, token) => {
      return params[token] ?? `{${token}}`;
    });
  };

  const value = useMemo(
    () => ({
      language,
      setLanguage,
      t,
      languageOptions,
    }),
    [language]
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage() {
  const context = useContext(LanguageContext);

  if (!context) {
    throw new Error("useLanguage must be used within a LanguageProvider");
  }

  return context;
}

export { languageOptions };
