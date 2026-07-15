import React, { useCallback, useEffect, useRef, useState } from "react";
import { useLanguage } from "../context/LanguageContext";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { buildIndianPlaceSuggestions } from "./indianPlacesData";

const DEFAULT_CENTER = [20.5937, 78.9629];

const LocationMapPicker = ({
  latitude,
  longitude,
  location,
  onLocationChange,
  onCoordinatesChange,
  onWeatherRefresh,
}) => {
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const { t } = useLanguage();
  const [searchTerm, setSearchTerm] = useState(location || "");
  const [suggestions, setSuggestions] = useState([]);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);

  const updateSelection = useCallback(
    async (lat, lng, displayName) => {
      onCoordinatesChange(lat, lng);
      onLocationChange(displayName || `${lat.toFixed(4)}, ${lng.toFixed(4)}`);
      onWeatherRefresh(lat, lng);
    },
    [onCoordinatesChange, onLocationChange, onWeatherRefresh]
  );

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

    return `${(fallbackLat ?? DEFAULT_CENTER[0]).toFixed(4)}, ${(fallbackLng ?? DEFAULT_CENTER[1]).toFixed(4)}`;
  }, []);

  const reverseGeocode = useCallback(async (lat, lng) => {
    try {
      const response = await fetch(
        `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lng}`
      );
      const data = await response.json();
      return formatLocationLabel(data, lat, lng);
    } catch {
      return `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
    }
  }, [formatLocationLabel]);

  const isCityLikeSuggestion = useCallback((suggestion) => {
    const address = suggestion.address || {};
    const primaryPlaceName =
      address.city ||
      address.town ||
      address.village ||
      address.municipality ||
      address.hamlet ||
      address.suburb ||
      address.county;

    const placeType = (suggestion.type || "").toLowerCase();
    const placeClass = (suggestion.class || "").toLowerCase();
    const countryCode = (suggestion.address?.country_code || "").toLowerCase();

    const isIndianPlace = countryCode === "in";
    const isPlaceLike =
      placeClass === "place" ||
      ["city", "town", "village", "municipality", "hamlet", "suburb"].includes(placeType);

    return Boolean(primaryPlaceName) && isIndianPlace && isPlaceLike;
  }, []);

  const getSuggestionLabel = useCallback((suggestion) => {
    const address = suggestion.address || {};
    const primaryPlaceName =
      address.city ||
      address.town ||
      address.village ||
      address.municipality ||
      address.hamlet ||
      address.suburb ||
      suggestion.name ||
      suggestion.display_name;

    const parts = [];
    if (primaryPlaceName) parts.push(primaryPlaceName);

    const districtName = address.county || address.district || address.state_district || address.city_district || "";
    if (districtName && districtName.toLowerCase() !== primaryPlaceName?.toLowerCase()) {
      parts.push(districtName);
    }

    const countryName = address.country || "";
    if (countryName) parts.push(countryName);

    return parts.join(", ");
  }, []);

  const fetchLocationSuggestions = useCallback(async (query) => {
    const localSuggestions = buildIndianPlaceSuggestions(query);
    if (localSuggestions.length > 0) {
      return localSuggestions;
    }

    try {
      const url = new URL("https://nominatim.openstreetmap.org/search");
      url.searchParams.set("format", "jsonv2");
      url.searchParams.set("limit", "5");
      url.searchParams.set("addressdetails", "1");
      url.searchParams.set("accept-language", "en");
      url.searchParams.set("dedupe", "1");
      url.searchParams.set("q", query);
      url.searchParams.set("countrycodes", "in");
      url.searchParams.set("viewbox", "68.186248,37.070000,97.402560,8.065000");
      url.searchParams.set("bounded", "1");

      const response = await fetch(url.toString());
      const data = await response.json();
      return data.filter(isCityLikeSuggestion);
    } catch {
      return [];
    }
  }, [isCityLikeSuggestion]);

  useEffect(() => {
    if (!mapRef.current) {
      const initialLat = latitude ?? DEFAULT_CENTER[0];
      const initialLng = longitude ?? DEFAULT_CENTER[1];

      mapRef.current = L.map("location-map-picker", {
        zoomControl: true,
      }).setView([initialLat, initialLng], 5);

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors",
      }).addTo(mapRef.current);

      markerRef.current = L.marker([initialLat, initialLng], {
        draggable: true,
        icon: L.divIcon({
          html: '<div style="background:#2563eb;width:16px;height:16px;border-radius:9999px;border:3px solid white;box-shadow:0 0 0 3px rgba(37,99,235,0.2);"></div>',
          className: "",
          iconSize: [16, 16],
          iconAnchor: [8, 8],
        }),
      }).addTo(mapRef.current);

      markerRef.current.on("dragend", async () => {
        const { lat, lng } = markerRef.current.getLatLng();
        const displayName = await reverseGeocode(lat, lng);
        updateSelection(lat, lng, displayName);
      });

      mapRef.current.on("click", async (event) => {
        const { lat, lng } = event.latlng;
        markerRef.current.setLatLng([lat, lng]);
        const displayName = await reverseGeocode(lat, lng);
        updateSelection(lat, lng, displayName);
      });
    }

    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
      markerRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (markerRef.current && mapRef.current) {
      const nextLatLng = L.latLng(latitude ?? DEFAULT_CENTER[0], longitude ?? DEFAULT_CENTER[1]);
      markerRef.current.setLatLng(nextLatLng);
      mapRef.current.panTo(nextLatLng);
    }
  }, [latitude, longitude]);

  useEffect(() => {
    const trimmedQuery = searchTerm.trim();
    if (!trimmedQuery || trimmedQuery.length < 1) {
      setSuggestions([]);
      return undefined;
    }

    const timeoutId = setTimeout(async () => {
      setLoadingSuggestions(true);
      try {
        const results = await fetchLocationSuggestions(trimmedQuery);
        setSuggestions(results);
      } catch {
        setSuggestions([]);
      } finally {
        setLoadingSuggestions(false);
      }
    }, 180);

    return () => clearTimeout(timeoutId);
  }, [fetchLocationSuggestions, searchTerm]);

  const handleSuggestionSelect = async (suggestion) => {
    const lat = parseFloat(suggestion.lat);
    const lng = parseFloat(suggestion.lon);
    const displayName = getSuggestionLabel(suggestion);
    setSearchTerm(displayName);
    setSuggestions([]);
    if (mapRef.current && markerRef.current) {
      const nextLatLng = L.latLng(lat, lng);
      markerRef.current.setLatLng(nextLatLng);
      mapRef.current.setView(nextLatLng, 12);
    }
    updateSelection(lat, lng, displayName);
  };

  return (
    <div className="space-y-2">
      <input
        type="text"
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        placeholder={t("enterLocation")}
        className="w-full p-2.5 border border-gray-300 rounded-lg focus:ring-1 focus:ring-blue-500 focus:border-blue-500 transition-all duration-300 hover:border-blue-300 text-sm"
      />
      {loadingSuggestions && <div className="text-xs text-gray-500">{t("searching")}</div>}
      {suggestions.length > 0 && (
        <ul className="max-h-32 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-sm text-sm">
          {suggestions.map((suggestion) => (
            <li key={suggestion.place_id || `${suggestion.lat}-${suggestion.lon}`}>
              <button
                type="button"
                onClick={() => handleSuggestionSelect(suggestion)}
                className="w-full text-left px-3 py-2 hover:bg-blue-50 transition-colors"
              >
                {getSuggestionLabel(suggestion)}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div
        id="location-map-picker"
        className="w-full h-60 rounded-lg border border-gray-300 bg-gray-100 shadow-inner transition-all duration-300 hover:shadow-md"
      ></div>
      {location && (
        <div className="text-xs text-gray-600 p-2 bg-white rounded border">
          {t("selected")}: {location}
        </div>
      )}
    </div>
  );
};

export default LocationMapPicker;
