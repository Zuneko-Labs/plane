/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import ICU from "i18next-icu";
import resourcesToBackend from "i18next-resources-to-backend";
import { SUPPORTED_LANGUAGES, FALLBACK_LANGUAGE, LANGUAGE_STORAGE_KEY } from "../constants/language";
import { NAMESPACES, DEFAULT_NAMESPACE } from "../constants/namespaces";

import type { i18n as I18nInstance } from "i18next";

export const i18nInstance: I18nInstance = i18n.createInstance();

// Locale JSON ships as static assets alongside the bundled chunk, so the base URL
// is resolved from the module URL at runtime.
const LOCALES_BASE_URL = new URL("./locales/", import.meta.url);

i18nInstance
  .use(ICU)
  .use(initReactI18next)
  .use(
    resourcesToBackend(async (language: string, namespace: string) => {
      // Fetched rather than dynamically imported: the bundler leaves this path to be
      // resolved at runtime, and browsers refuse to execute a JSON response as an ES
      // module without an import attribute. That rejection is swallowed by the
      // backend, leaving i18next with no resources and rendering raw keys.
      const response = await fetch(new URL(`${language}/${namespace}.json`, LOCALES_BASE_URL).href);
      if (!response.ok) {
        throw new Error(`Failed to load locale ${language}/${namespace}: ${response.status}`);
      }
      return response.json();
    })
  );

const initialLng =
  typeof window !== "undefined" ? localStorage.getItem(LANGUAGE_STORAGE_KEY) || FALLBACK_LANGUAGE : FALLBACK_LANGUAGE;

export const initPromise = i18nInstance
  .init({
    lng: initialLng,
    fallbackLng: FALLBACK_LANGUAGE,
    supportedLngs: SUPPORTED_LANGUAGES.map((l) => l.value),
    ns: NAMESPACES,
    defaultNS: DEFAULT_NAMESPACE,
    // fallbackNS ensures all namespaces are searched for any key, so components
    // don't need to pass NAMESPACES to useTranslation (which triggers re-render cascades).
    fallbackNS: NAMESPACES.filter((ns) => ns !== DEFAULT_NAMESPACE),
    partialBundledLanguages: true,
    keySeparator: ".",
    nsSeparator: false,
    interpolation: { escapeValue: false },
    returnNull: false,
    returnEmptyString: false,
    // Pinned explicitly even though it's the default — i18next-icu intercepts the
    // format pipeline and returns raw objects regardless of this flag, so the runtime
    // guard in useTranslation is what actually prevents React crashes. Documenting
    // intent here so this isn't accidentally flipped.
    returnObjects: false,
    react: { useSuspense: false },
  })
  // Eagerly pre-load all namespaces for the initial language so they're cached
  // before any component renders. This prevents the re-render cascade that occurs
  // when react-i18next triggers concurrent async loads for unloaded namespaces.
  .then(() => i18nInstance.loadNamespaces(NAMESPACES));
