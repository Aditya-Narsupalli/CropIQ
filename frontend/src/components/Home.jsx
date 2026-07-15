import React, { useState, useEffect, useRef } from "react";
import { GiFarmTractor, GiWheat, GiCottonFlower } from "react-icons/gi";
import {
  FaLeaf,
  FaChartLine,
  FaStore,
  FaMicrophone,
  FaMapMarkerAlt,
  FaMobileAlt,
  FaRobot,
  FaCloudSun,
  FaSearchLocation,
  FaRupeeSign,
  FaUsersCog,
  FaProjectDiagram,
  FaEnvelope,
} from "react-icons/fa";
import { MdOutlineAgriculture } from "react-icons/md";
import { Link } from "react-router-dom";
import Lottie from "lottie-react";

// Simplified animation component
const FadeInSection = ({ children, delay = 0 }) => {
  const [isVisible, setVisible] = useState(false);
  const domRef = useRef();

  useEffect(() => {
    const { current } = domRef;
    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) {
        setVisible(true);
        observer.disconnect();
      }
    });

    if (current) observer.observe(current);
    return () => {
      if (current) observer.unobserve(current);
    };
  }, []);

  return (
    <div
      ref={domRef}
      className="transition-all duration-1000 ease-in-out"
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

// Simple hover card
const FeatureCard = ({ icon, title, description, onLearnMore }) => {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <div
      className={`bg-white rounded-xl shadow-lg p-8 border border-gray-100 transition-all duration-300 ${
        isHovered ? "transform -translate-y-2 shadow-xl" : ""
      }`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className="inline-block p-4 bg-green-100 rounded-xl text-green-900 mb-4">
        {icon}
      </div>
      <h3 className="text-xl font-bold mb-3 text-green-900">{title}</h3>
      <p className="text-gray-600">{description}</p>

      {isHovered && (
        <div className="mt-4">
          <button 
            onClick={onLearnMore}
            className="text-green-700 font-medium flex items-center hover:text-green-900 transition"
          >
            Learn more
            <svg
              className="w-4 h-4 ml-1"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M9 5l7 7-7 7"
              />
            </svg>
          </button>
        </div>
      )}
    </div>
  );
};

// Feature Details Modal
const FeatureModal = ({ feature, onClose }) => {
  if (!feature) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl max-w-3xl w-full max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-green-900 text-white p-6 flex justify-between items-center">
          <h2 className="text-3xl font-bold">{feature.title}</h2>
          <button 
            onClick={onClose}
            className="text-2xl hover:text-green-200 transition"
          >
            ✕
          </button>
        </div>

        <div className="p-6 md:p-8">
          {/* Feature Details */}
          <div className="mb-8">
            <h3 className="text-2xl font-bold text-green-900 mb-4">Overview</h3>
            <p className="text-gray-700 text-lg leading-relaxed">{feature.details}</p>
          </div>

          {/* Key Features */}
          <div className="mb-8">
            <h3 className="text-2xl font-bold text-green-900 mb-4">Key Features</h3>
            <ul className="space-y-3">
              {feature.keyFeatures.map((feature, idx) => (
                <li key={idx} className="flex items-start">
                  <span className="text-green-600 mr-3 font-bold">✓</span>
                  <span className="text-gray-700">{feature}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* FAQs */}
          <div>
            <h3 className="text-2xl font-bold text-green-900 mb-4">Frequently Asked Questions</h3>
            <div className="space-y-4">
              {feature.faqs.map((faq, idx) => (
                <details key={idx} className="border border-green-200 rounded-lg">
                  <summary className="p-4 bg-green-50 cursor-pointer font-semibold text-green-900 hover:bg-green-100 transition">
                    {faq.question}
                  </summary>
                  <div className="p-4 text-gray-700 bg-white">
                    {faq.answer}
                  </div>
                </details>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

const Home = () => {
  const [animationData, setAnimationData] = useState(null);
  const [selectedFeature, setSelectedFeature] = useState(null);

  // Feature details with FAQs
  const featureDetails = {
    "Market Intelligence": {
      title: "Market Intelligence",
      details: "Access real-time and historical mandi prices for your crops across all major Indian states. Our AI-powered price forecasts and market trend analysis help you make informed selling decisions. We use verified AgMarkNet data to ensure accuracy and reliability.",
      keyFeatures: [
        "Real-time mandi prices for all major crops",
        "AI-powered price forecasts for next 7-30 days",
        "Historical price trends and seasonal patterns",
        "Market analysis for every Indian state",
        "Government subsidy tracking",
        "Direct buyer connections"
      ],
      faqs: [
        {
          question: "How frequently is the market data updated?",
          answer: "Our market data is updated daily from AgMarkNet and other official sources. Prices reflect real-time trading information from mandis across India."
        },
        {
          question: "Does FarmGenius work in regions without internet connectivity?",
          answer: "For best experience, an internet connection is recommended. We're working on offline features for low-connectivity regions."
        },
        {
          question: "How accurate are the price forecasts?",
          answer: "Our AI forecasts are typically 85-92% accurate based on historical patterns, weather, and seasonal factors. Actual prices may vary due to market dynamics."
        }
      ]
    },
    "AI Yield Prediction": {
      title: "AI Yield Prediction",
      details: "Our advanced AI model predicts your harvest yield with high accuracy by analyzing weather patterns, soil conditions, satellite imagery, and your exact farm location. Get actionable recommendations to boost yield and reduce crop loss risks.",
      keyFeatures: [
        "Yield prediction with 85%+ accuracy",
        "Weather pattern analysis for your location",
        "Soil condition assessment",
        "Satellite-based farm monitoring",
        "Actionable tips to improve yield",
        "Risk assessment and mitigation strategies"
      ],
      faqs: [
        {
          question: "What data is needed for accurate yield prediction?",
          answer: "We use weather data, historical yield records, soil properties, and satellite imagery. The more data you provide, the more accurate our predictions become."
        },
        {
          question: "How far in advance can predictions be made?",
          answer: "Predictions are most accurate 2-4 weeks before harvest. We provide updates throughout the growing season as new data becomes available."
        },
        {
          question: "Can I compare predicted vs. actual yield?",
          answer: "Yes, after harvest, you can log your actual yield and our system learns to improve future predictions for your specific farm."
        }
      ]
    },
    "Disease & Pest Diagnosis": {
      title: "Disease & Pest Diagnosis",
      details: "Simply take a photo of your crop with any disease or pest symptoms, and our advanced computer vision AI instantly identifies the issue. Get region-specific treatment and prevention advice in your local language.",
      keyFeatures: [
        "Instant disease and pest identification",
        "Photo-based diagnosis using computer vision",
        "Treatment recommendations tailored to your region",
        "Preventive measures and best practices",
        "Multilingual guidance (English, Hindi, Marathi)",
        "Connection to local agricultural experts"
      ],
      faqs: [
        {
          question: "How accurate is the disease detection?",
          answer: "Our AI model achieves 90%+ accuracy in identifying common crop diseases and pests. For confirmation, we can connect you with local agricultural experts."
        },
        {
          question: "What photo quality is needed for diagnosis?",
          answer: "A clear photo of the affected leaf or area in good lighting works best. Blurry or dark images may reduce accuracy."
        },
        {
          question: "Does it work for all crops?",
          answer: "We currently support major crops like wheat, rice, cotton, sugarcane, and vegetables. We're continuously adding more crops."
        }
      ]
    },
    "Voice & Chat Assistant": {
      title: "Voice & Chat Assistant",
      details: "Talk to FarmGenius in your preferred language - English, Hindi, or Marathi. Ask questions, get step-by-step farming guidance, and receive expert support hands-free, anytime and anywhere on your farm.",
      keyFeatures: [
        "Voice-based interaction in 3 languages",
        "Step-by-step farming guidance",
        "Expert Q&A about crops and techniques",
        "Hands-free operation while working",
        "24/7 availability",
        "Context-aware responses"
      ],
      faqs: [
        {
          question: "Is the voice assistant available in regional languages?",
          answer: "Yes, we support English, Hindi, and Marathi. More regional languages are coming soon."
        },
        {
          question: "Does it work on low-bandwidth connections?",
          answer: "Our voice system is optimized for 2G/3G networks, though 4G provides the best experience."
        },
        {
          question: "Can I save conversations for reference?",
          answer: "Yes, all conversations are saved in your account history and can be reviewed anytime."
        }
      ]
    },
    "Weather & Climate Alerts": {
      title: "Weather & Climate Alerts",
      details: "Plan your farm work with hyper-local weather forecasts, rainfall predictions, and extreme weather alerts. Stay prepared and take protective measures before adverse weather impacts your crops.",
      keyFeatures: [
        "Hyper-local weather forecasts for your farm",
        "Rainfall predictions with 90%+ accuracy",
        "Extreme weather alerts (hail, frost, storm)",
        "Seasonal planning recommendations",
        "Historical weather patterns",
        "Real-time weather notifications"
      ],
      faqs: [
        {
          question: "How accurate are the weather forecasts?",
          answer: "Our 5-day forecasts are 90%+ accurate. Longer forecasts become less precise due to weather variability."
        },
        {
          question: "Will I get alerts before a storm?",
          answer: "Yes, we send push notifications for severe weather events in your area at least 2-4 hours in advance."
        },
        {
          question: "Can I set custom alerts for temperature or rainfall?",
          answer: "Yes, you can customize alerts based on your crop's specific weather needs."
        }
      ]
    },
    "Multi-Agent AI System": {
      title: "Multi-Agent AI System",
      details: "Our unique multi-agent architecture combines specialized AI agents that work together seamlessly. Each agent focuses on a specific domain—yield prediction, disease detection, market analysis, and weather forecasting—ensuring you get the most expert and accurate advice for every farming scenario.",
      keyFeatures: [
        "Specialized agents for different farming domains",
        "Collaborative decision-making for better results",
        "Context-aware recommendations",
        "Real-time coordination between agents",
        "Continuous learning from farm data",
        "Adaptive strategies based on your farm's profile"
      ],
      faqs: [
        {
          question: "What makes the multi-agent system better?",
          answer: "Each agent is trained specifically for its domain, resulting in more accurate specialized advice. The agents work together to provide holistic farming solutions."
        },
        {
          question: "How do the agents communicate?",
          answer: "Our agents share context and data seamlessly through the Model Context Protocol, ensuring consistent and comprehensive advice across all farming areas."
        },
        {
          question: "Can I interact with individual agents?",
          answer: "Yes, you can use any feature independently, but the real power comes from having all agents work together for integrated recommendations."
        }
      ]
    },
    "Model Context Protocol": {
      title: "Model Context Protocol",
      details: "Our proprietary Model Context Protocol (MCP) ensures all AI modules maintain complete awareness of your farm's context. This means every interaction, recommendation, and prediction is informed by comprehensive farm data, historical patterns, and your specific agricultural profile.",
      keyFeatures: [
        "Unified context across all AI modules",
        "Historical farm data integration",
        "Real-time context updates",
        "Personalized recommendations",
        "Seamless data flow between services",
        "Privacy-preserving context management"
      ],
      faqs: [
        {
          question: "How does context improve recommendations?",
          answer: "By maintaining complete farm context, each recommendation is tailored to your specific location, crops, soil, weather patterns, and historical data—not generic advice."
        },
        {
          question: "What data is included in the context?",
          answer: "Weather history, soil conditions, previous yields, crop types, market prices, disease occurrences, and all your interactions with CropIQ."
        },
        {
          question: "Is my farm data secure?",
          answer: "Yes, all data is encrypted and stored securely. You have full control over what data is used and can delete it anytime."
        }
      ]
    },
    "Market Access & Finance": {
      title: "Market Access & Finance",
      details: "Connect directly with premium buyers and mandis for your produce. Access government subsidy information, loan calculators, and financial planning tools designed specifically for farmers. Make informed decisions about when and where to sell for maximum profit.",
      keyFeatures: [
        "Direct connections to verified buyers and mandis",
        "Government subsidy tracking and eligibility checker",
        "Loan and credit calculator for farm investments",
        "Financial planning tools for farm management",
        "Market rate comparisons across regions",
        "Transaction history and profit tracking"
      ],
      faqs: [
        {
          question: "How do I connect with buyers through CropIQ?",
          answer: "Our platform matches your produce with verified buyers and mandis based on quantity, quality, and location. You can negotiate directly through our secure interface."
        },
        {
          question: "What subsidies can I check?",
          answer: "We provide information on government subsidies for seeds, fertilizers, equipment, irrigation, and other farming inputs at both state and national levels."
        },
        {
          question: "Can I use the loan calculator?",
          answer: "Yes, our calculator helps you understand available loans, interest rates, repayment schedules, and which schemes you may be eligible for based on your farm profile."
        }
      ]
    }
  };

  useEffect(() => {
    fetch("/animations/hero.json")
      .then((response) => response.json())
      .then((data) => setAnimationData(data))
      .catch((error) => console.error("Error loading animation:", error));

    // Add this to fix any default body/html margins
    document.body.style.margin = "0";
    document.body.style.padding = "0";
    document.documentElement.style.margin = "0";
    document.documentElement.style.padding = "0";

    return () => {
      // Clean up when component unmounts
      document.body.style.margin = "";
      document.body.style.padding = "";
      document.documentElement.style.margin = "";
      document.documentElement.style.padding = "";
    };
  }, []);

  return (
    <div className="font-sans text-gray-800">
      {/* Hero Section - Full height for mobile and properly centered for desktop */}
      <header className="bg-gradient-to-r from-green-900 via-green-800 to-green-900 text-white relative min-h-screen pt-16 sm:pt-20 flex items-center">
        {/* Professional subtle background pattern */}
        <div className="absolute inset-0 opacity-10">
          <svg
            className="h-full w-full"
            width="100%"
            height="100%"
            xmlns="http://www.w3.org/2000/svg"
          >
            <defs>
              <pattern
                id="grid"
                width="40"
                height="40"
                patternUnits="userSpaceOnUse"
              >
                <path
                  d="M 40 0 L 0 0 0 40"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1"
                />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#grid)" />
          </svg>
        </div>

        {/* Subtle leaf accents - more professional positioning */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          {[...Array(3)].map((_, i) => (
            <div
              key={i}
              className="absolute text-green-400"
              style={{
                left: `${65 + i * 12}%`,
                top: `${20 + i * 25}%`,
                opacity: 0.15,
                transform: `rotate(${i * 45}deg) scale(${1 + i * 0.5})`,
              }}
            >
              <FaLeaf className="text-4xl" />
            </div>
          ))}
        </div>

        {/* Main container with proper centering for desktop and no gaps for mobile */}
        <div className="max-w-7xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-12">
          <div className="flex flex-col lg:flex-row items-center justify-between">
            <div className="lg:w-1/2 mb-12 lg:mb-0 pr-0 lg:pr-12">
              <FadeInSection>
                <div className="flex items-center mb-4">
                  <div className="h-1 w-12 bg-green-400 rounded mr-4"></div>
                  <span className="uppercase tracking-wider text-green-300 font-medium">
                    AI-Powered Agriculture
                  </span>
                </div>
                <h1 className="text-4xl sm:text-5xl font-bold tracking-tight mb-6 leading-tight">
                  <span className="block">Intelligent Farming</span>
                  <span className="block text-green-300">
                    for Better Harvests
                  </span>
                </h1>
              </FadeInSection>

              <FadeInSection delay={200}>
                <p className="text-lg sm:text-xl mb-8 text-green-50 leading-relaxed">
                  Leverage advanced artificial intelligence to maximize crop
                  yields, detect diseases early, and connect with premium
                  markets—all in one comprehensive platform designed for modern
                  farmers.
                </p>
              </FadeInSection>
            </div>
            <div className="lg:w-1/2 flex justify-center">
              <FadeInSection delay={300}>
                <div className="relative">
                  {/* Background decorative elements */}
                  <div className="absolute -left-6 -top-6 w-64 h-64 bg-green-700 rounded-full opacity-20 blur-xl"></div>
                  <div className="absolute -right-8 -bottom-8 w-40 h-40 bg-green-500 rounded-full opacity-20 blur-xl"></div>

                  {/* Animation container */}
                  <div className="relative overflow-hidden h-96 sm:w-80 md:w-96">
                    {animationData ? (
                      <Lottie
                        animationData={animationData}
                        loop={true}
                        autoplay={true}
                        style={{ width: "100%", height: "100%" }}
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center bg-green-50">
                        <GiFarmTractor className="text-8xl text-green-600" />
                        <div className="absolute inset-0 bg-gradient-to-br from-transparent to-green-100 opacity-50"></div>
                      </div>
                    )}
                  </div>
                </div>
              </FadeInSection>
            </div>
          </div>
        </div>
      </header>
      {/* Features Section */}
      <section className="py-20 px-4 sm:px-6 lg:px-8 bg-white">
        <div className="max-w-7xl mx-auto">
          <FadeInSection>
            <div className="text-center mb-16">
              <h2 className="text-3xl sm:text-4xl font-bold text-green-900 mb-4">
                Powered by Advanced AI
              </h2>
              <p className="text-xl text-gray-600 max-w-3xl mx-auto">
                CropIQ combines multiple AI technologies to provide
                comprehensive farming assistance powered by machine learning and deep analytics.
              </p>
            </div>
          </FadeInSection>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
            {/* Feature 1: Market Analytics */}
            <FadeInSection delay={100}>
              <FeatureCard
                icon={<FaChartLine className="text-4xl text-green-700" />} 
                title="Market Intelligence"
                description="Get real-time and historical mandi prices for your crops, AI-powered price forecasts, and market trend analysis for every major Indian state. Make the smartest selling decisions using verified AgMarkNet data."
                onLearnMore={() => setSelectedFeature(featureDetails["Market Intelligence"])}
              />
            </FadeInSection>

            {/* Feature 2: AI Yield Prediction */}
            <FadeInSection delay={200}>
              <FeatureCard
                icon={<MdOutlineAgriculture className="text-4xl text-amber-700" />} 
                title="AI Yield Prediction"
                description="Predict your harvest with confidence! Our AI analyzes weather, soil, and satellite data for your exact farm location. Get actionable tips to boost yield and reduce risk."
                onLearnMore={() => setSelectedFeature(featureDetails["AI Yield Prediction"])}
              />
            </FadeInSection>

            {/* Feature 3: Disease & Pest Detection */}
            <FadeInSection delay={300}>
              <FeatureCard
                icon={<FaLeaf className="text-4xl text-green-800" />} 
                title="Disease & Pest Diagnosis"
                description="Snap a photo of your crop—instantly detect diseases and pests using advanced computer vision. Receive region-specific treatment and prevention advice, in your language."
                onLearnMore={() => setSelectedFeature(featureDetails["Disease & Pest Diagnosis"])}
              />
            </FadeInSection>

            {/* Feature 4: Multi-Agent Intelligence */}
            <FadeInSection delay={400}>
              <FeatureCard
                icon={<FaUsersCog className="text-4xl text-purple-700" />} 
                title="Multi-Agent AI System"
                description="Benefit from our unique multi-agent approach—specialized AI agents collaborate to provide the best advice, predictions, and support for every farming scenario."
                onLearnMore={() => setSelectedFeature(featureDetails["Multi-Agent AI System"])}
              />
            </FadeInSection>

            {/* Feature 5: Model Context Protocol */}
            <FadeInSection delay={500}>
              <FeatureCard
                icon={<FaProjectDiagram className="text-4xl text-cyan-700" />} 
                title="Model Context Protocol"
                description="Enjoy seamless, context-aware assistance. Our Model Context Protocol ensures all AI modules share knowledge and context, delivering more accurate and personalized recommendations."
                onLearnMore={() => setSelectedFeature(featureDetails["Model Context Protocol"])}
              />
            </FadeInSection>

            {/* Feature 6: Voice & Chat Assistant */}
            <FadeInSection delay={600}>
              <FeatureCard
                icon={<FaMicrophone className="text-4xl text-green-600" />} 
                title="Voice & Chat Assistant"
                description="Talk to CropIQ in English, Hindi, or Marathi. Get expert answers, step-by-step guidance, and farming support hands-free—anytime, anywhere."
                onLearnMore={() => setSelectedFeature(featureDetails["Voice & Chat Assistant"])}
              />
            </FadeInSection>

            {/* Feature 7: Weather Insights */}
            <FadeInSection delay={700}>
              <FeatureCard
                icon={<FaCloudSun className="text-4xl text-blue-500" />} 
                title="Weather & Climate Alerts"
                description="Plan your farm work with hyper-local forecasts, rainfall predictions, and extreme weather alerts. Stay prepared and protect your crops from climate risks."
                onLearnMore={() => setSelectedFeature(featureDetails["Weather & Climate Alerts"])}
              />
            </FadeInSection>

            {/* Feature 8: Market Access & Finance */}
            <FadeInSection delay={800}>
              <FeatureCard
                icon={<FaRupeeSign className="text-4xl text-amber-600" />} 
                title="Market Access & Finance"
                description="Discover the best mandi or buyer for your produce, track government subsidies, and access loan calculators—all in one place."
                onLearnMore={() => setSelectedFeature(featureDetails["Market Access & Finance"])}
              />
            </FadeInSection>
          </div>
        </div>
      </section>
      {/* Footer */}
      <footer className="bg-gray-100 py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
            <div>
                <div className="flex items-center space-x-2 text-green-900 font-extrabold text-xl mb-4">
                <div className="bg-green-900 p-2 rounded-full">
                  <GiFarmTractor className="text-2xl text-white" />
                </div>
                <span>CropIQ</span>
              </div>
              <p className="text-gray-600 mb-4">
                AI-powered assistance for sustainable agriculture and improved
                livelihoods.
              </p>
              <div className="mt-4">
                <h3 className="text-lg font-bold text-green-900 mb-2">Contact Us</h3>
                <a
                  href="mailto:adityanarsupalli8@gmail.com"
                  onClick={(e) => {
                    e.preventDefault();
                    const email = "adityanarsupalli8@gmail.com";
                    window.location.href = `mailto:${email}`;
                    setTimeout(() => {
                      window.open(
                        `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(email)}`,
                        "_blank",
                        "noopener,noreferrer"
                      );
                    }, 250);
                  }}
                  className="inline-flex items-center text-green-900 hover:text-green-700 font-medium"
                >
                  <FaEnvelope className="mr-2" />
                  adityanarsupalli8@gmail.com
                </a>
              </div>
            </div>

          </div>

              <div className="mt-12 pt-8 border-t border-gray-200">
            <p className="text-gray-500 text-center">
              2025 CropIQ. All rights reserved.
            </p>
          </div>
        </div>
      </footer>
      <FeatureModal 
        feature={selectedFeature} 
        onClose={() => setSelectedFeature(null)} 
      />
    </div>
  );
};

export default Home;
