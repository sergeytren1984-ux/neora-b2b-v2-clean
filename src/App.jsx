import React, { useState } from "react";

const FORMSPREE_ENDPOINT = "https://formspree.io/f/mrbonpno";

const t = {
  fr: {
    lang: "FR",
    switchTo: "EN",

    brand: "NÉORA",
    heroTitle: "Lot d’essai pour HoReCa",
    heroSubtitle: "Torréfaction de spécialité pour cafés et restaurants à Paris.",

    sections: {
      general: "1. Informations générales sur l’établissement",
      currentCoffee: "2. Informations sur votre café actuel",
      priceBlock: "3. Bloc Prix",
      volume: "4. Volume mensuel",
      collaboration: "5. Disponibilité / Collaboration",
    },

    general: {
      cafeName: "Nom du café / établissement",
      address: "Adresse complète",
      contactPerson: "Personne de contact (propriétaire / manager)",
      email: "Email professionnel",
      phone: "Téléphone",
    },

    current: {
      supplierLabel: "Fournisseur actuel (marque / torréfacteur)",
      originLabel: "Origine utilisée habituellement (pays / région)",
      roastProfileLabel: "Profil de torréfaction utilisé",
      roastOptions: {
        espresso: "Espresso",
        omni: "Omni",
        filter: "Filtre",
      },
    },

    price: {
      q1Title: "Question 1 — Prix d’achat habituel (1 kg spécialité)",
      q1Name: "price_current",
      q1Options: [
        "Jusqu’à 22 €/kg",
        "22–24 €/kg",
        "24–26 €/kg",
        "26–28 €/kg",
        "28+ €/kg",
      ],

      q2Title: "Question 2 — Prix souhaité pour un café 83+ pts (qualité stable)",
      q2Name: "price_expected",
      q2Options: [
        "≤ 23 €/kg",
        "23–25 €/kg",
        "25–27 €/kg",
        "27–29 €/kg",
        "À étudier individuellement",
      ],

      q3Title: "Question 3 — Prix jugé trop élevé (achat impossible)",
      q3Name: "price_too_high",
      q3Options: ["24 €/kg", "26 €/kg", "28 €/kg", "30 €/kg"],
    },

    volume: {
      title: "Volume mensuel",
      name: "volume_monthly",
      options: [
        "Jusqu’à 10 kg",
        "10–20 kg",
        "20–35 kg",
        "35–50 kg",
        "50–100 kg",
        "100+ kg",
      ],
    },

    collab: {
      readyTitle: "Prêt à tester notre café ?",
      readyName: "ready_to_test",
      readyOptions: ["Oui", "Peut-être", "Non"],

      contactTitle: "Mode de contact préféré",
      contactName: "contact_method",
      contactOptions: ["Téléphone", "Email", "WhatsApp", "Visite en personne"],
    },

    submit: "Envoyer la demande",

    right: {
      lotTitle: "Lot d’essai — qu’est-ce que c’est ?",
      lotBullets: [
        "Un lot d’essai personnalisé de cafés de spécialité pour votre établissement.",
        "3 références possibles (espresso / filtre) selon votre profil et vos volumes.",
        "Un sourcing transparent et une torréfaction pensée pour la HoReCa parisienne.",
      ],
      assortmentTitle: "Notre assortiment",
      assortmentText:
        "Sélection de cafés de spécialité (Brésil, Colombie, Honduras, Éthiopie selon récolte) en profils espresso et filtre, adaptée à la restauration.",
      whyTitle: "Pourquoi nous ?",
      whyBullets: [
        "Profil de tasse stable et reproductible.",
        "Process B2B simple : facturation mensuelle, livraison sur Paris.",
        "Accompagnement dans la transition depuis votre torréfacteur actuel.",
      ],
      termsTitle: "Conditions",
      termsBullets: [
        "Volumes d’essai flexibles selon votre débit.",
        "Livraison sur Paris intra-muros sous 24–72 h.",
        "Support pour calibrage espresso / filtre si besoin.",
      ],
    },
  },

  en: {
    lang: "EN",
    switchTo: "FR",

    brand: "NÉORA",
    heroTitle: "Trial batch for HoReCa",
    heroSubtitle: "Specialty coffee roasting for cafés and restaurants in Paris.",

    sections: {
      general: "1. Venue information",
      currentCoffee: "2. Your current coffee",
      priceBlock: "3. Price block",
      volume: "4. Monthly volume",
      collaboration: "5. Readiness to collaborate",
    },

    general: {
      cafeName: "Name of café / venue",
      address: "Full address",
      contactPerson: "Contact person (owner / manager)",
      email: "Business email",
      phone: "Phone",
    },

    current: {
      supplierLabel: "Current supplier (brand / roaster)",
      originLabel: "Origin usually used (country / region)",
      roastProfileLabel: "Roast profile used",
      roastOptions: {
        espresso: "Espresso",
        omni: "Omni",
        filter: "Filter",
      },
    },

    price: {
      q1Title: "Question 1 — Usual purchase price (1 kg specialty)",
      q1Name: "price_current",
      q1Options: [
        "Up to 22 €/kg",
        "22–24 €/kg",
        "24–26 €/kg",
        "26–28 €/kg",
        "28+ €/kg",
      ],

      q2Title:
        "Question 2 — Desired price for 83+ pts coffee (stable quality)",
      q2Name: "price_expected",
      q2Options: [
        "≤ 23 €/kg",
        "23–25 €/kg",
        "25–27 €/kg",
        "27–29 €/kg",
        "Case-by-case discussion",
      ],

      q3Title: "Question 3 — Price that is too high (no purchase)",
      q3Name: "price_too_high",
      q3Options: ["24 €/kg", "26 €/kg", "28 €/kg", "30 €/kg"],
    },

    volume: {
      title: "Monthly volume",
      name: "volume_monthly",
      options: [
        "Up to 10 kg",
        "10–20 kg",
        "20–35 kg",
        "35–50 kg",
        "50–100 kg",
        "100+ kg",
      ],
    },

    collab: {
      readyTitle: "Ready to test our coffee?",
      readyName: "ready_to_test",
      readyOptions: ["Yes", "Maybe", "No"],

      contactTitle: "Preferred way to contact you",
      contactName: "contact_method",
      contactOptions: ["Phone", "Email", "WhatsApp", "In-person visit"],
    },

    submit: "Send request",

    right: {
      lotTitle: "Trial batch — what is it?",
      lotBullets: [
        "A tailored trial batch of specialty coffee for your venue.",
        "Up to 3 references (espresso / filter) depending on your profile and volumes.",
        "Transparent sourcing and roasting designed for Paris HoReCa.",
      ],
      assortmentTitle: "Our assortment",
      assortmentText:
        "Selection of specialty coffees (Brazil, Colombia, Honduras, Ethiopia depending on harvest) in espresso and filter profiles, tailored for restaurants.",
      whyTitle: "Why us?",
      whyBullets: [
        "Stable and repeatable cup profile.",
        "Simple B2B process: monthly invoicing, delivery in Paris.",
        "Support when switching from your current roaster.",
      ],
      termsTitle: "Terms",
      termsBullets: [
        "Flexible trial volumes depending on your consumption.",
        "Delivery in inner Paris within 24–72 h.",
        "Support for espresso / filter calibration if needed.",
      ],
    },
  },
};

export default function App() {
  const [lang, setLang] = useState("fr");
  const tr = t[lang];

  return (
    <div className="min-h-screen bg-neutral-50 text-neutral-900">
      <header className="border-b border-neutral-200">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-5">
          <div className="text-sm tracking-[0.35em] font-semibold">
            {tr.brand}
          </div>
          <button
            type="button"
            onClick={() => setLang(lang === "fr" ? "en" : "fr")}
            className="text-xs font-medium tracking-wide border border-neutral-300 rounded-full px-3 py-1 hover:bg-neutral-100 transition"
          >
            {tr.lang} · {tr.switchTo}
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-10">
        <div className="mb-10 max-w-3xl">
          <h1 className="mb-3 text-3xl font-semibold tracking-tight md:text-4xl">
            {tr.heroTitle}
          </h1>
          <p className="text-sm md:text-base text-neutral-700">
            {tr.heroSubtitle}
          </p>
        </div>

        <div className="grid gap-10 md:grid-cols-[minmax(0,2fr)_minmax(0,1.1fr)]">
          {/* ЛЕВЫЙ СТОЛБЕЦ — ФОРМА */}
          <form
            method="POST"
            action={FORMSPREE_ENDPOINT}
            className="space-y-8 bg-white rounded-2xl shadow-sm border border-neutral-200 px-5 py-6 md:px-7 md:py-7"
          >
            <input type="hidden" name="lang" value={lang} />

            {/* 1. ОБЩАЯ ИНФА */}
            <section>
              <h2 className="mb-4 text-sm font-semibold tracking-wide uppercase text-neutral-800">
                {tr.sections.general}
              </h2>
              <div className="space-y-4">
                <TextField
                  label={tr.general.cafeName}
                  name="cafe_name"
                  required
                />
                <TextField
                  label={tr.general.address}
                  name="cafe_address"
                  required
                />
                <TextField
                  label={tr.general.contactPerson}
                  name="contact_person"
                  required
                />
                <TextField
                  label={tr.general.email}
                  name="email"
                  type="email"
                  required
                />
                <TextField
                  label={tr.general.phone}
                  name="phone"
                  type="tel"
                  required
                />
              </div>
            </section>

            {/* 2. ТЕКУЩИЙ КОФЕ */}
            <section>
              <h2 className="mb-4 text-sm font-semibold tracking-wide uppercase text-neutral-800">
                {tr.sections.currentCoffee}
              </h2>
              <div className="space-y-4">
                <TextField
                  label={tr.current.supplierLabel}
                  name="current_supplier"
                />
                <TextField
                  label={tr.current.originLabel}
                  name="current_origin"
                />

                <fieldset className="space-y-2">
                  <legend className="mb-1 text-xs font-medium text-neutral-700">
                    {tr.current.roastProfileLabel}
                  </legend>
                  <RadioGroup
                    name="roast_profile"
                    options={[
                      tr.current.roastOptions.espresso,
                      tr.current.roastOptions.omni,
                      tr.current.roastOptions.filter,
                    ]}
                  />
                </fieldset>
              </div>
            </section>

            {/* 3. ЦЕНОВОЙ БЛОК */}
            <section>
              <h2 className="mb-4 text-sm font-semibold tracking-wide uppercase text-neutral-800">
                {tr.sections.priceBlock}
              </h2>

              <div className="space-y-5">
                <fieldset className="space-y-2">
                  <legend className="mb-1 text-xs font-medium text-neutral-700">
                    {tr.price.q1Title}
                  </legend>
                  <RadioGroup
                    name={tr.price.q1Name}
                    options={tr.price.q1Options}
                  />
                </fieldset>

                <fieldset className="space-y-2">
                  <legend className="mb-1 text-xs font-medium text-neutral-700">
                    {tr.price.q2Title}
                  </legend>
                  <RadioGroup
                    name={tr.price.q2Name}
                    options={tr.price.q2Options}
                  />
                </fieldset>

                <fieldset className="space-y-2">
                  <legend className="mb-1 text-xs font-medium text-neutral-700">
                    {tr.price.q3Title}
                  </legend>
                  <RadioGroup
                    name={tr.price.q3Name}
                    options={tr.price.q3Options}
                  />
                </fieldset>
              </div>
            </section>

            {/* 4. ОБЪЁМ */}
            <section>
              <h2 className="mb-3 text-sm font-semibold tracking-wide uppercase text-neutral-800">
                {tr.sections.volume}
              </h2>
              <fieldset className="space-y-2">
                <legend className="sr-only">{tr.volume.title}</legend>
                <RadioGroup
                  name={tr.volume.name}
                  options={tr.volume.options}
                />
              </fieldset>
            </section>

            {/* 5. ГОТОВНОСТЬ */}
            <section>
              <h2 className="mb-4 text-sm font-semibold tracking-wide uppercase text-neutral-800">
                {tr.sections.collaboration}
              </h2>

              <div className="space-y-4">
                <fieldset className="space-y-2">
                  <legend className="mb-1 text-xs font-medium text-neutral-700">
                    {tr.collab.readyTitle}
                  </legend>
                  <RadioGroup
                    name={tr.collab.readyName}
                    options={tr.collab.readyOptions}
                  />
                </fieldset>

                <fieldset className="space-y-2">
                  <legend className="mb-1 text-xs font-medium text-neutral-700">
                    {tr.collab.contactTitle}
                  </legend>
                  <RadioGroup
                    name={tr.collab.contactName}
                    options={tr.collab.contactOptions}
                  />
                </fieldset>
              </div>
            </section>

            <div className="pt-2">
              <button
                type="submit"
                className="w-full rounded-full bg-neutral-900 px-5 py-3 text-sm font-medium tracking-wide text-white hover:bg-black focus:outline-none focus:ring-2 focus:ring-neutral-800 focus:ring-offset-2 focus:ring-offset-white transition"
              >
                {tr.submit}
              </button>
            </div>
          </form>

          {/* ПРАВЫЙ СТОЛБЕЦ — ИНФО */}
          <aside className="space-y-8 text-sm text-neutral-800">
            <section>
              <h3 className="mb-2 text-base font-semibold">
                {tr.right.lotTitle}
              </h3>
              <ul className="space-y-1 list-disc pl-5">
                {tr.right.lotBullets.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>

            <section>
              <h3 className="mb-2 text-base font-semibold">
                {tr.right.assortmentTitle}
              </h3>
              <p className="text-sm text-neutral-700">
                {tr.right.assortmentText}
              </p>
            </section>

            <section>
              <h3 className="mb-2 text-base font-semibold">
                {tr.right.whyTitle}
              </h3>
              <ul className="space-y-1 list-disc pl-5">
                {tr.right.whyBullets.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>

            <section>
              <h3 className="mb-2 text-base font-semibold">
                {tr.right.termsTitle}
              </h3>
              <ul className="space-y-1 list-disc pl-5">
                {tr.right.termsBullets.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          </aside>
        </div>
      </main>
    </div>
  );
}

function TextField(props) {
  const { label, name, type = "text", required } = props;
  return (
    <label className="block text-xs font-medium text-neutral-700">
      <span className="mb-1 inline-block">{label}</span>
      <input
        type={type}
        name={name}
        required={required}
        className="mt-1 w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm outline-none ring-0 transition placeholder:text-neutral-400 focus:border-neutral-900 focus:ring-1 focus:ring-neutral-900"
      />
    </label>
  );
}

function RadioGroup(props) {
  const { name, options } = props;
  return (
    <div className="space-y-1">
      {options.map((opt) => (
        <label
          key={opt}
          className="flex items-center gap-2 text-xs text-neutral-800"
        >
          <input
            type="radio"
            name={name}
            value={opt}
            className="h-3.5 w-3.5 border-neutral-400 text-neutral-900 focus:ring-neutral-900"
          />
          <span>{opt}</span>
        </label>
      ))}
    </div>
  );
}
