import React, { useEffect, useState } from "react";
import { useLanguage } from "../../context/LanguageContext";
import { getMarketPricesApi, getMarketTrendsApi } from "../../services/api";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import {
  FaChartBar,
  FaChartLine,
  FaSearch,
  FaDownload,
  FaSpinner,
  FaTimes,
} from "react-icons/fa";
import { GiWheat } from "react-icons/gi";

const MarketView = () => {
  const [marketData, setMarketData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedCrop, setSelectedCrop] = useState("");
  const [isFetchingCrop, setIsFetchingCrop] = useState(false);
  const [trendData, setTrendData] = useState("");
  const [historicalPriceData, setHistoricalPriceData] = useState([]);
  const [trendSignal, setTrendSignal] = useState(null);
  const [sortDirection, setSortDirection] = useState("desc");
  const [filterValue, setFilterValue] = useState("");
  const [priceChangeData, setPriceChangeData] = useState({});
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage, setItemsPerPage] = useState(5);
  const { t } = useLanguage();

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const pricesJson = await getMarketPricesApi();
        setMarketData(pricesJson.market_data || []);

        // price_change_pct now comes from the live Agmarknet API
        // (today's price vs. yesterday's), no more random mock values.
        const changes = {};
        pricesJson.market_data.forEach((item) => {
          changes[item.crop] =
            item.price_change_pct !== undefined && item.price_change_pct !== null
              ? item.price_change_pct
              : 0;
        });
        setPriceChangeData(changes);

        setError("");
      } catch (err) {
        console.error("Market data fetch error:", err);
        setError(`Failed to load market data: ${err.message}`);
      }
      setLoading(false);
    };
    fetchData();
  }, []);

  const fetchTrendData = async (crop) => {
    if (!crop) return;

    setIsFetchingCrop(true);
    setSelectedCrop(crop);
    setTrendData("");
    setHistoricalPriceData([]);
    setTrendSignal(null);

    try {
      const data = await getMarketTrendsApi(crop);
      if (data && typeof data === "object") {
        setTrendData(data.message || "No trend summary available.");
        setHistoricalPriceData(data.historical_data || []);
        if (data.confidence && data.confidence !== "none") {
          setTrendSignal({
            score: data.trend_score,
            label: data.trend_label,
            confidence: data.confidence,
            advisory: data.advisory,
          });
        }
      } else {
        setTrendData("Error: Unexpected API response format.");
        setHistoricalPriceData([]);
      }
    } catch (err) {
      setTrendData(`Could not fetch trend data: ${err.message}`);
      setHistoricalPriceData([]);
    }

    setIsFetchingCrop(false);
  };

  const sortMarketData = () => {
    const newDirection = sortDirection === "asc" ? "desc" : "asc";
    setSortDirection(newDirection);

    const sortedData = [...marketData].sort((a, b) => {
      const priceA = a.price_per_quintal || a.price_per_tonne || 0;
      const priceB = b.price_per_quintal || b.price_per_tonne || 0;

      return newDirection === "asc" ? priceA - priceB : priceB - priceA;
    });

    setMarketData(sortedData);
  };

  const filteredMarketData = marketData.filter((item) =>
    item.crop.toLowerCase().includes(filterValue.toLowerCase())
  );

  const indexOfLastItem = currentPage * itemsPerPage;
  const indexOfFirstItem = indexOfLastItem - itemsPerPage;
  const currentItems = filteredMarketData.slice(
    indexOfFirstItem,
    indexOfLastItem
  );
  const totalPages = Math.ceil(filteredMarketData.length / itemsPerPage);

  const handlePageChange = (pageNumber) => {
    setCurrentPage(pageNumber);
    window.scrollTo({
      top: 600,
      behavior: "smooth",
    });
  };

  const exportToCSV = () => {
    const headers = ["Crop", "Price", "Location", "Date"];

    const csvData = filteredMarketData.map((item) => [
      item.crop,
      item.price_per_quintal
        ? `₹${item.price_per_quintal}/quintal`
        : item.price_per_tonne
        ? `₹${item.price_per_tonne}/tonne`
        : "-",
      item.location,
      item.date,
    ]);

    const csvContent = [
      headers.join(","),
      ...csvData.map((row) => row.join(",")),
    ].join("\n");

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);

    link.setAttribute("href", url);
    link.setAttribute(
      "download",
      `market_prices_${new Date().toISOString().split("T")[0]}.csv`
    );
    link.style.display = "none";

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-amber-50 via-green-50 to-emerald-50 pt-24 pb-12 px-4">
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
        {/* Header with static logo (no animation) */}
        <div className="text-center mb-10 w-full">
          <div
            className="inline-flex items-center justify-center p-5 bg-gradient-to-r from-amber-100 to-green-100 rounded-full text-green-600 mb-5 shadow-md mx-auto"
            style={{ width: "80px", height: "80px" }}
          >
            <FaChartLine className="text-4xl" />
          </div>
          <h1 className="text-3xl md:text-4xl font-extrabold mb-3 text-amber-900 bg-clip-text text-transparent bg-gradient-to-r from-amber-700 to-green-700">
            {t("marketPriceDashboard")}
          </h1>
          <p className="text-gray-600 max-w-xl md:max-w-2xl mx-auto text-sm md:text-base">
            {t("marketPriceDashboardDescription")}
          </p>
          {!loading && marketData.length > 0 && (() => {
            // Agmarknet itself has real reporting lag (its own website can
            // show data that's a day or more old) - surface that plainly
            // instead of implying these are always today's prices.
            const latestDate = marketData.reduce(
              (max, item) => (item.date > max ? item.date : max),
              marketData[0]?.date || ""
            );
            if (!latestDate) return null;
            const daysOld = Math.round(
              (new Date().setHours(0, 0, 0, 0) - new Date(latestDate).setHours(0, 0, 0, 0)) / 86400000
            );
            if (daysOld <= 0) return null;
            return (
              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-full inline-block px-3 py-1 mt-2">
                Prices as of {latestDate} ({daysOld} day{daysOld > 1 ? "s" : ""} ago) - Agmarknet hasn't published newer data yet
              </p>
            );
          })()}
        </div>

        {/* Main Content */}
        <div className="bg-white rounded-xl shadow-lg p-6 md:p-8 border border-amber-100 relative overflow-hidden">
          {/* Subtle background pattern */}
          <div className="absolute top-0 left-0 w-full h-full opacity-5 pointer-events-none">
            <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
              <pattern
                id="pattern-market"
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
                fill="url(#pattern-market)"
              />
            </svg>
          </div>

          {/* Content */}
          {loading ? (
            <div className="flex justify-center items-center h-64">
              <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-green-700"></div>
            </div>
          ) : error ? (
            <div className="bg-red-50 border-l-4 border-red-500 p-4 rounded-r-lg shadow-md">
              <div className="flex items-center">
                <FaTimes className="text-red-500 mr-3 text-xl" />
                <div>
                  <h3 className="text-sm font-medium text-red-800">
                    Data Loading Error
                  </h3>
                  <p className="mt-1 text-sm text-red-700">{error}</p>
                </div>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
              {/* Left Column - Market Data */}
              <div className="space-y-6">
                {/* Price Visualization Card */}
                <div className="bg-white p-6 rounded-lg shadow-sm border border-amber-100">
                  <div className="flex justify-between items-center mb-4">
                    <h3 className="font-semibold text-lg text-gray-800 flex items-center">
                      <FaChartBar className="mr-2 text-green-500" />
                      Current Market Prices
                    </h3>
                    <div className="flex space-x-2">
                      <button
                        onClick={sortMarketData}
                        className="px-3 py-1 text-sm bg-amber-100 hover:bg-amber-200 text-amber-800 rounded-full flex items-center"
                      >
                        <span>{t("sort")} {sortDirection === "asc" ? "↑" : "↓"}</span>
                      </button>
                      <button
                        onClick={exportToCSV}
                        className="px-3 py-1 text-sm bg-blue-100 hover:bg-blue-200 text-blue-800 rounded-full flex items-center"
                      >
                        <FaDownload className="mr-1" />
                        <span>{t("export")}</span>
                      </button>
                    </div>
                  </div>

                  {/* Filter Input */}
                  <div className="mb-4 relative">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                      <FaSearch className="text-gray-400" />
                    </div>
                    <input
                      type="text"
                      placeholder={t("filterByCropName")}
                      value={filterValue}
                      onChange={(e) => setFilterValue(e.target.value)}
                      className="w-full pl-10 pr-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-amber-500"
                    />
                  </div>

                  <ResponsiveContainer width="100%" height={300}>
                    <BarChart
                      data={filteredMarketData}
                      margin={{
                        top: 5,
                        right: 30,
                        left: 20,
                        bottom: 5,
                      }}
                    >
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis
                        dataKey="crop"
                        angle={-15}
                        textAnchor="end"
                        height={60}
                        interval={0}
                        fontSize={10}
                      />
                      <YAxis />
                      <Tooltip formatter={(value) => [`₹${value}`, "Price"]} />
                      <Legend />
                      <Bar
                        dataKey="price_per_quintal"
                        fill="#10B981"
                        name={t("pricePerQuintal")}
                      />
                      <Bar
                        dataKey="price_per_tonne"
                        fill="#3B82F6"
                        name={t("pricePerTonne")}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>

                {/* Market Data Table Card */}
                <div className="bg-white p-6 rounded-lg shadow-sm border border-amber-100">
                  <div className="flex justify-between items-center mb-4">
                    <h3 className="font-semibold text-lg text-gray-800 flex items-center">
                      <FaChartBar className="mr-2 text-green-500" />
                      Detailed Price Data
                    </h3>
                    <div className="flex items-center space-x-2">
                      <select
                        className="text-sm border border-gray-300 rounded p-1 focus:outline-none focus:ring-2 focus:ring-amber-500"
                        value={itemsPerPage}
                        onChange={(e) => {
                          setItemsPerPage(Number(e.target.value));
                          setCurrentPage(1);
                        }}
                      >
                        <option value={5}>5 {t("itemsPerPage")}</option>
                        <option value={10}>10 {t("itemsPerPage")}</option>
                        <option value={15}>15 {t("itemsPerPage")}</option>
                      </select>
                    </div>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-green-200 border border-green-100 rounded-lg shadow-sm">
                      <thead className="bg-green-50">
                        <tr className="bg-green-100 text-green-800">
                          <th className="px-4 py-3 text-left font-semibold rounded-tl-lg">
                            {t("home") /* reuse simple label from translations */}
                          </th>
                          <th className="px-4 py-3 text-left font-semibold">
                            {t("price")}
                          </th>
                          <th className="px-4 py-3 text-left font-semibold">
                            {t("change")}
                          </th>
                          <th className="px-4 py-3 text-left font-semibold">
                            {t("locationLabel")}
                          </th>
                          <th className="px-4 py-3 text-left font-semibold rounded-tr-lg">
                            {t("date")}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {currentItems.map((item, index) => (
                          <tr
                            key={item.id}
                            className={`border-b border-green-50 hover:bg-green-50 ${
                              index % 2 === 0 ? "bg-white" : "bg-green-25"
                            }`}
                          >
                            <td
                              className="px-4 py-3 font-medium cursor-pointer hover:text-green-700"
                              onClick={() =>
                                fetchTrendData(item.crop.split(" (")[0])
                              }
                            >
                              {item.crop}
                            </td>
                            <td className="px-4 py-3">
                              {item.price_per_quintal
                                ? `₹${item.price_per_quintal}/quintal`
                                : item.price_per_tonne
                                ? `₹${item.price_per_tonne}/tonne`
                                : "-"}
                            </td>
                            <td className="px-4 py-3">
                              {priceChangeData[item.crop] > 0 ? (
                                <span className="text-green-600 font-medium flex items-center">
                                  <svg
                                    xmlns="http://www.w3.org/2000/svg"
                                    className="h-4 w-4 mr-1"
                                    viewBox="0 0 20 20"
                                    fill="currentColor"
                                  >
                                    <path
                                      fillRule="evenodd"
                                      d="M12 7a1 1 0 01-1-1V3.414l-8.293 8.293a1 1 0 01-1.414-1.414l10-10a.997.997 0 011.414 0 .999.999 0 01.293.707V6a1 1 0 01-1 1z"
                                      clipRule="evenodd"
                                    />
                                  </svg>
                                  +{priceChangeData[item.crop]}%
                                </span>
                              ) : priceChangeData[item.crop] < 0 ? (
                                <span className="text-red-600 font-medium flex items-center">
                                  <svg
                                    xmlns="http://www.w3.org/2000/svg"
                                    className="h-4 w-4 mr-1"
                                    viewBox="0 0 20 20"
                                    fill="currentColor"
                                  >
                                    <path
                                      fillRule="evenodd"
                                      d="M12 13a1 1 0 001 1h2.586l-8.293 8.293a1 1 0 01-1.414-1.414l10-10A.997.997 0 0116.586 10a.999.999 0 01.707.293V14a1 1 0 01-1 1h-4z"
                                      clipRule="evenodd"
                                    />
                                  </svg>
                                  {priceChangeData[item.crop]}%
                                </span>
                              ) : (
                                <span className="text-gray-500 font-medium">
                                  0%
                                </span>
                              )}
                            </td>
                            <td className="px-4 py-3">{item.location}</td>
                            <td className="px-4 py-3">{item.date}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Pagination Controls */}
                  {filteredMarketData.length > 0 && (
                    <div className="flex justify-between items-center mt-4 px-2">
                      <div className="text-sm text-gray-600">
                        Showing {indexOfFirstItem + 1}-
                        {Math.min(indexOfLastItem, filteredMarketData.length)}{" "}
                        of {filteredMarketData.length} items
                      </div>
                      <div className="flex space-x-1">
                        <button
                          onClick={() => handlePageChange(currentPage - 1)}
                          disabled={currentPage === 1}
                          className={`px-3 py-1 rounded-md text-sm ${
                            currentPage === 1
                              ? "bg-gray-100 text-gray-400 cursor-not-allowed"
                              : "bg-amber-100 text-amber-800 hover:bg-amber-200"
                          }`}
                        >
                          Previous
                        </button>
                        {Array.from(
                          { length: Math.min(5, totalPages) },
                          (_, i) => {
                            let pageNum;
                            if (totalPages <= 5) {
                              pageNum = i + 1;
                            } else if (currentPage <= 3) {
                              pageNum = i + 1;
                            } else if (currentPage >= totalPages - 2) {
                              pageNum = totalPages - 4 + i;
                            } else {
                              pageNum = currentPage - 2 + i;
                            }

                            return (
                              <button
                                key={pageNum}
                                onClick={() => handlePageChange(pageNum)}
                                className={`w-8 h-8 rounded-full text-sm ${
                                  currentPage === pageNum
                                    ? "bg-amber-600 text-white"
                                    : "bg-amber-50 text-amber-800 hover:bg-amber-100"
                                }`}
                              >
                                {pageNum}
                              </button>
                            );
                          }
                        )}
                        <button
                          onClick={() => handlePageChange(currentPage + 1)}
                          disabled={currentPage === totalPages}
                          className={`px-3 py-1 rounded-md text-sm ${
                            currentPage === totalPages
                              ? "bg-gray-100 text-gray-400 cursor-not-allowed"
                              : "bg-amber-100 text-amber-800 hover:bg-amber-200"
                          }`}
                        >
                          Next
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Right Column - Trend Analysis */}
              <div className="space-y-6">
                {/* Trend Analysis Card */}
                <div className="bg-white p-6 rounded-lg shadow-sm border border-amber-100">
                  <h3 className="font-semibold text-lg text-gray-800 mb-4 flex items-center">
                    <FaChartLine className="mr-2 text-green-500" />
                    Market Trend Analysis
                  </h3>
                  <div className="flex flex-wrap gap-2 mb-4">
                    {[
                      ...new Set(
                        marketData.map((item) => item.crop.split(" (")[0])
                      ),
                    ].map((cropName) => (
                      <button
                        key={cropName}
                        onClick={() => fetchTrendData(cropName)}
                        className={`mr-2 mb-2 px-3 py-1 rounded-full text-sm transition-colors ${
                          selectedCrop === cropName
                            ? "bg-green-700 text-white"
                            : "bg-green-100 text-green-800 hover:bg-green-200"
                        }`}
                        disabled={isFetchingCrop && selectedCrop === cropName}
                      >
                        {cropName}
                      </button>
                    ))}
                  </div>
                  {selectedCrop && (
                    <div className="mt-4 p-4 bg-blue-50 rounded-lg border border-blue-200">
                      <h4 className="font-semibold text-blue-800 mb-2">
                        {t("trendSummary", { crop: selectedCrop })}
                      </h4>
                      {isFetchingCrop ? (
                        <div className="flex items-center justify-center p-4">
                          <FaSpinner className="animate-spin text-green-600 mr-2" />
                          <span>Loading trend data...</span>
                        </div>
                      ) : (
                        <p className="text-gray-700">{trendData}</p>
                      )}

                      {trendSignal && !isFetchingCrop && (
                        <div className="mt-3 p-3 bg-white rounded-lg border border-gray-200">
                          <div className="flex items-center gap-2 mb-2">
                            <span
                              className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                                trendSignal.label === "Upward"
                                  ? "bg-green-100 text-green-700"
                                  : trendSignal.label === "Downward"
                                  ? "bg-red-100 text-red-700"
                                  : "bg-gray-100 text-gray-700"
                              }`}
                            >
                              {trendSignal.label} ({trendSignal.score > 0 ? "+" : ""}
                              {trendSignal.score}%)
                            </span>
                            <span className="text-xs text-gray-500">
                              Confidence: {trendSignal.confidence}
                            </span>
                          </div>
                          <p className="text-xs text-gray-600">{trendSignal.advisory}</p>
                        </div>
                      )}

                      {/* Historical Price Chart */}
                      {historicalPriceData.length > 0 && !isFetchingCrop && (
                        <div className="mt-4">
                          <h5 className="font-semibold text-blue-700 mb-2 text-sm">
                            Price Trend (Real Recorded Days)
                          </h5>
                          <div className="h-64">
                            <ResponsiveContainer width="100%" height="100%">
                              <LineChart
                                data={historicalPriceData}
                                margin={{
                                  top: 5,
                                  right: 30,
                                  left: 20,
                                  bottom: 5,
                                }}
                              >
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis
                                  dataKey="date"
                                  fontSize={10}
                                  tickFormatter={(tick) => tick.slice(5)}
                                />
                                <YAxis
                                  domain={["auto", "auto"]}
                                  fontSize={10}
                                />
                                <Tooltip
                                  formatter={(value) => [
                                    `₹${value.toFixed(2)}`,
                                    "Price",
                                  ]}
                                />
                                <Legend />
                                <Line
                                  type="monotone"
                                  dataKey="price"
                                  stroke="#8884d8"
                                  activeDot={{ r: 8 }}
                                  name="Price"
                                />
                              </LineChart>
                            </ResponsiveContainer>
                          </div>
                        </div>
                      )}

                      {/* Market Alerts - uses the REAL day-over-day change
                          from priceChangeData (populated from Agmarknet's
                          own price_change_pct). Previously this looked up
                          `selectedCrop + " (Maharashtra)"`, a key that never
                          existed in priceChangeData (which is keyed by plain
                          crop name) - so the lookup always failed and fell
                          back to a hardcoded "5%", shown as if real, for
                          every single crop regardless of actual data. Also
                          mislabeled a day-over-day figure as "in the last
                          week". Fixed to use the correct key, the accurate
                          timeframe, and to say so honestly when there's no
                          real change data instead of fabricating one. */}
                      {selectedCrop && !isFetchingCrop && (
                        <div className="mt-4 pt-4 border-t border-blue-200">
                          <div className="flex justify-between items-center mb-2">
                            <h5 className="font-semibold text-blue-700 text-sm">
                              {t("marketAlerts")}
                            </h5>
                            <button className="text-xs bg-green-100 text-green-800 px-2 py-1 rounded-full hover:bg-green-200">
                              {t("setPriceAlert")}
                            </button>
                          </div>
                          {(() => {
                            // Primary source: today's live Agmarknet fetch.
                            // Fallback: compute a real day-over-day change
                            // from the last two points of the historical
                            // store we already loaded for the chart - Agmarknet
                            // not including a crop in *today's* live snapshot
                            // doesn't mean we have no real recent data for it,
                            // we might just need to look at our own recorded
                            // history instead of only today's live fetch.
                            let pct = priceChangeData[selectedCrop];
                            let source = "today's live Agmarknet data";
                            if ((pct === undefined || pct === null || pct === 0) && historicalPriceData.length >= 2) {
                              const prev = historicalPriceData[historicalPriceData.length - 2].price;
                              const curr = historicalPriceData[historicalPriceData.length - 1].price;
                              if (prev) {
                                pct = Math.round(((curr - prev) / prev) * 1000) / 10;
                                source = "our recorded price history";
                              }
                            }
                            if (pct !== undefined && pct !== null && pct !== 0) {
                              return (
                                <div className="bg-yellow-50 border-l-4 border-yellow-400 p-3 rounded">
                                  <p className="text-sm text-yellow-800">
                                    Price for <strong>{selectedCrop}</strong> has{" "}
                                    {pct > 0 ? "risen" : "fallen"}{" "}
                                    {Math.abs(pct)}% since yesterday (based on {source}).
                                  </p>
                                </div>
                              );
                            }
                            return (
                              <p className="text-sm text-gray-500">
                                No real day-over-day change data available for {selectedCrop} right now.
                              </p>
                            );
                          })()}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Market Recommendations card removed - it was entirely
                    static text ("Soybean is showing consistent price growth
                    in Maharashtra markets", "Turmeric prices are expected to
                    rise due to increased export demand", etc.), shown
                    identically regardless of any real data, date, or actual
                    crop performance. A genuine version of this would need to
                    compare analyze_trend_signal's real trend_score across
                    all crops to find an actual best/worst performer - worth
                    building properly later, but not worth faking in the
                    meantime. */}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default MarketView;
