import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "../locales/en.json";

export const defaultNS = "translation";

void i18n.use(initReactI18next).init({
  lng: "en",
  fallbackLng: "en",
  resources: { en: { translation: en } },
  // React already escapes rendered strings.
  interpolation: { escapeValue: false },
  returnNull: false,
});

export default i18n;
