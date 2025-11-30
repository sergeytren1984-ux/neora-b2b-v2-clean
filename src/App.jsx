import React, { useState } from "react";

const FORMSPREE_ENDPOINT = "https://formspree.io/f/mrbonpno";

const t = {
  fr: {
    lang: "FR",
    switchTo: "EN",

    heroTitle: "Lot d’essai pour HoReCa",
    heroSubtitle: "Torréfaction de spécialité pour cafés et restaurants à Paris.",

    sections: {
      general: "Informations générales sur l’établissement",
      currentCoffee: "Informations sur votre café actuel",
      priceBlock: "Bloc Prix (optionnel)",
      volume: "Volume mensuel",
      collaboration: "Disponibilité / Collaboration",
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
      q1Title: "Prix d’achat habituel (1 kg spécialité)",
      q1Name: "price_current",
      q1Options: [
        "Jusqu’à 22 €/kg",
        "22–24 €/kg",
        "24–26 €/kg",
        "26–28 €/kg",
        "28+ €/kg",
      ],

      q2Title:
        "Prix souhaité pour un café 83+ pts (qualité stable)",
      q2Name: "price_expected",
      q2Options: [
        "≤ 23 €/kg",
        "23–25 €/kg",
        "25–27 €/kg",
        "27–29 €/kg",
        "À étudier individuellement",
      ],

      q3Title: "Prix jugé trop élevé (achat impossible)",
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

    priceToggleShow: "Afficher les questions détaillées sur le prix",
    priceToggleHide: "Masquer le bloc prix",
    priceHint:
      "Bloc optionnel : si vous avez le temps, ces questions nous aident à adapter l’offre.",

    submit: "Envoyer la demande",

    right: {
      lotTitle: "Comment est composé le lot ?",
      lotBullets: [
        "Trois paquets d’essai de 250 g (origines / terroirs variés), profils espresso.",
        "Torréfaction la semaine de l’envoi ; chaque lot avec profil et date.",
        "Retour d’expérience : ce qui a plu / moins plu — on fixe ensuite le profil pour les livraisons régulières.",
      ],
      assortmentTitle: "Notre assortiment",
      assortmentText:
        "Cafés de spécialité (Brésil, Colombie, Honduras, Éthiopie selon récolte), profils espresso et filtre pour la restauration.",
      whyTitle: "Pourquoi nous ?",
      whyBullets: [
        "Qualité stable, profils clairs.",
        "Prix B2B transparents.",
        "Livraison rapide sur Paris.",
      ],
      termsTitle: "Conditions",
      termsBullets: [
        "Volumes d’essai flexibles selon votre débit.",
        "Livraison intra-muros sous 24–72 h.",
        "Support pour calibrage espresso / filtre si besoin.",
      ],
    },
  },

  en: {
    lang: "EN",
    switchTo: "FR",

    heroTitle: "Trial batch for HoReCa",
    heroSubtitle: "Specialty coffee roasting for cafés and restaurants in Paris.",

    sections: {
      general: "Venue information",
      currentCoffee: "Your current coffee",
      priceBlock: "Price block (optional)",
      volume: "Monthly volume",
      collaboration: "Readiness to collaborate",
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
      q1Title: "Usual purchase price (1 kg specialty)",
      q1Name: "price_current",
      q1Options: [
        "Up to 22 €/kg",
        "22–24 €/kg",
        "24–26 €/kg",
        "26–28 €/kg",
        "28+ €/kg",
      ],

      q2Title:
        "Desired price for 83+ pts coffee (stable quality)",
      q2Name: "price_expected",
      q2Options: [
        "≤ 23 €/kg",
        "23–25 €/kg",
        "25–27 €/kg",
        "27–29 €/kg",
        "Case-by-case discussion",
      ],

      q3Title: "Price that is too high (no purchase)",
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

    priceToggleShow: "Show detailed price questions",
    priceToggleHide: "Hide price block",
    priceHint:
      "Optional block: if you have time, these questions help us fine-tune the offer.",

    submit: "Send request",

    right: {
      lotTitle: "How is the trial batch composed?",
      lotBullets: [
        "Three 250 g trial bags (different origins / terroirs), espresso profiles.",
        "Roasted in the week of shipping; each lot with profile and roast date.",
        "Feedback session: what you liked / didn’t like — we lock the profile for regular deliveries.",
      ],
      assortmentTitle: "Our assortment",
      assortmentText:
        "Specialty coffees (Brazil, Colombia, Honduras, Ethiopia depending on harvest), espresso and filter profiles for restaurants.",
      whyTitle: "Why us?",
      whyBullets: [
        "Stable quality, clear profiles.",
        "Transparent B2B pricing.",
        "Fast delivery within Paris.",
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
  const [lang, setLang] = useState<"fr" | "en">("fr");
  const [showPrice, setShowPrice] = useState(false);
  const tr = t[lang];

  return (
    <div className="min-h-screen bg-[#f5f5f5] px-3 py-6 md:px-4 md:py-10">
      <div className="mx-auto max-w-5xl rounded-[32px] bg-white shadow-md border border-neutral-200 px-5 py-6 md:px-10 md:py-8">
        {/* HEADER ВНУТРИ КАРТОЧКИ */}
        <header className="mb-6 flex items-center justify-between">
          <div className="text-lg font-semibold tracking-[0.35em]">
            N<span className="text-[#C58A44]">É</span>ORA
          </div>
          <button
            type="button"
            onClick={() => setLang(lang === "fr" ? "en" : "fr")}
            className="rounded-full border border-neutral-300 px-3 py-1 text-xs font-medium tracking-wide hover:bg-neutral-100 transition"
          >
            {tr.lang} · {tr.switchTo}
          </button>
        </header>

        {/* HERO */}
        <div className="mb-7 max-w-xl">
          <h1 className="mb-2 text-2xl font-semibold tracking-tight md:text-3xl">
            {tr.heroTitle}
          </h1>
          <p className="text-sm md:text-[15px] text-neutral-700">
            {tr.heroSubtitle}
          </p>
        </div>

        {/* ДВЕ КОЛОНКИ КАК РАНЬШЕ */}
        <div className="grid gap-8 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          {/* ФОРМА */}
          <form
            method="POST"
            action={FORMSPREE_ENDPOINT}
            className="space-y-6"
          >
            <input type="hidden" name="lang" value={lang} />

            {/* 1. ОБЩАЯ ИНФА */}
            <section className="space-y-4">
              <h2 className="text-sm font-semibold text-neutral-900">
                {tr.sections.general}
              </h2>
              <div className="space-y-3">
                <TextField
                  label={tr.general.cafeName}
                  name="cafe_name"
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
                  label={tr.general.address}
                  name="cafe_address"
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
            <section className="space-y-3 pt-1 border-t border-neutral-200">
              <h2 className="pt-4 text-sm font-semibold text-neutral-900">
                {tr.sections.currentCoffee}
              </h2>
              <div className="space-y-3">
                <TextField
                  label={tr.current.supplierLabel}
                  name="current_supplier"
                />
                <TextField
                  label={tr.current.originLabel}
                  name="current_origin"
                />
                <fieldset className="space-y-2">
                  <legend className="text-xs font-medium text-neutral-700">
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

            {/* 3. ЦЕНОВОЙ БЛОК — СКРЫТ ПО УМОЛЧАНИЮ */}
            <section className="space-y-3 pt-1 border-t border-neutral-200">
              <div className="flex flex-col gap-2 pt-4">
                <h2 className="text-sm font-semibold text-neutral-900">
                  {tr.sections.priceBlock}
                </h2>
                <p className="text-xs text-neutral-500">{tr.priceHint}</p>
                <button
                  type="button"
                  onClick={() => setShowPrice((v) => !v)}
                  className="inline-flex w-max items-center justify-center rounded-full border border-neutral-300 px-3 py-1.5 text-xs font-medium text-neutral-800 hover:bg-neutral-100 transition"
                >
                  {showPrice ? tr.priceToggleHide : tr.priceToggleShow}
                </button>
              </div>

              {showPrice && (
                <div className="space-y-4">
                  <fieldset className="space-y-2">
                    <legend className="text-xs font-medium text-neutral-700">
                      {tr.price.q1Title}
                    </legend>
                    <RadioGroup
                      name={tr.price.q1Name}
                      options={tr.price.q1Options}
                    />
                  </fieldset>

                  <fieldset className="space-y-2">
                    <legend className="text-xs font-medium text-neutral-700">
                      {tr.price.q2Title}
                    </legend>
                    <RadioGroup
                      name={tr.price.q2Name}
                      options={tr.price.q2Options}
                    />
                  </fieldset>

                  <fieldset className="space-y-2">
                    <legend className="text-xs font-medium text-neutral-700">
                      {tr.price.q3Title}
                    </legend>
                    <RadioGroup
                      name={tr.price.q3Name}
                      options={tr.price.q3Options}
                    />
                  </fieldset>
                </div>
              )}
            </section>

            {/* 4. ОБЪЁМ */}
            <section className="space-y-3 pt-1 border-t border-neutral-200">
              <h2 className="pt-4 text-sm font-semibold text-neutral-900">
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
            <section className="space-y-4 pt-1 border-t border-neutral-200">
              <h2 className="pt-4 text-sm font-semibold text-neutral-900">
                {tr.sections.collaboration}
              </h2>
              <div className="space-y-3">
                <fieldset className="space-y-2">
                  <legend className="text-xs font-medium text-neutral-700">
                    {tr.collab.readyTitle}
                  </legend>
                  <RadioGroup
                    name={tr.collab.readyName}
                    options={tr.collab.readyOptions}
                  />
                </fieldset>

                <fieldset className="space-y-2">
                  <legend className="text-xs font-medium text-neutral-700">
                    {tr.collab.contactTitle}
                  </legend>
                  <RadioGroup
                    name={tr.collab.contactName}
                    options={tr.collab.contactOptions}
                  />
                </fieldset>
              </div>
            </section>

            {/* КНОПКА КАК РАНЬШЕ — ЗОЛОТАЯ */}
            <div className="pt-2">
              <button
                type="submit"
                className="w-full rounded-full bg-[#C58A44] px-5 py-3 text-sm font-semibold tracking-wide text-white hover:bg-[#b5783b] focus:outline-none focus:ring-2 focus:ring-[#C58A44] focus:ring-offset-2 focus:ring-offset-white transition"
              >
                {tr.submit}
              </button>
            </div>
          </form>

          {/* ПРАВЫЙ ИНФО-БЛОК — ЧИСТЫЙ, КАК БЫЛО */}
          <aside className="rounded-3xl border border-neutral-200 bg-neutral-50 px-4 py-4 md:px-6 md:py-6 text-sm text-neutral-800">
            <section className="mb-4">
              <h3 className="mb-2 text-sm font-semibold">
                {tr.right.lotTitle}
              </h3>
              <ul className="space-y-1 list-disc pl-5">
                {tr.right.lotBullets.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>

            <section className="mb-4">
              <h3 className="mb-2 text-sm font-semibold">
                {tr.right.assortmentTitle}
              </h3>
              <p className="text-xs text-neutral-700">
                {tr.right.assortmentText}
              </p>
            </section>

            <section className="mb-4">
              <h3 className="mb-2 text-sm font-semibold">
                {tr.right.whyTitle}
              </h3>
              <ul className="space-y-1 list-disc pl-5">
                {tr.right.whyBullets.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>

            <section>
              <h3 className="mb-2 text-sm font-semibold">
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
      </div>
    </div>
  );
}

type TextFieldProps = {
  label: string;
  name: string;
  type?: string;
  required?: boolean;
};

function TextField({ label, name, type = "text", required }: TextFieldProps) {
  return (
    <label className="block text-xs font-medium text-neutral-700">
      <span className="mb-1 inline-block">{label}</span>
      <input
        type={type}
        name={name}
        required={required}
        className="mt-0.5 w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm outline-none ring-0 transition placeholder:text-neutral-400 focus:border-[#C58A44] focus:ring-1 focus:ring-[#C58A44]"
      />
    </label>
  );
}

type RadioGroupProps = {
  name: string;
  options: string[];
};

function RadioGroup({ name, options }: RadioGroupProps) {
  return (
    <div className="flex flex-col gap-1">
      {options.map((opt) => (
        <label
          key={opt}
          className="flex items-center gap-2 text-xs text-neutral-800"
        >
          <input
            type="radio"
            name={name}
            value={opt}
            className="h-3.5 w-3.5 border-neutral-400 text-[#C58A44] focus:ring-[#C58A44]"
          />
          <span>{opt}</span>
        </label>
      ))}
    </div>
  );
}
