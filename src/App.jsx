import React, { useState } from "react";

const FORMSPREE_ENDPOINT = "https://formspree.io/f/mrbonpno";

const t = {
  fr: {
    lang: "FR",
    switchTo: "EN",
    hero: "Lot d’essai pour HoReCa",
    sub: "Torréfaction de spécialité pour cafés et restaurants à Paris.",
    cta: "Envoyer la demande",
    benefits: "Pourquoi nous ?",
    b1: "Qualité stable, profils clairs",
    b2: "Prix B2B transparents",
    b3: "Livraison rapide sur Paris",
    conditions: "Conditions",
    conditionsList: [
      "Volumes d’essai flexibles selon votre débit.",
      "Livraison sur Paris intra-muros sous 24–72 h.",
      "Support pour calibrage espresso / filtre si besoin."
    ],
    form: {
      company: "Nom du café / établissement",
      contact: "Personne de contact",
      email: "Email professionnel",
      phone: "Téléphone",
      address: "Adresse complète",
      volume: "Volume mensuel (kg)",
      priceTarget: "Prix cible pour 1 kg café spécialité (83+ pts)",
      currentRoaster: "Fournisseur actuel (marque / torréfacteur)",
      origin: "Origine utilisée habituellement (pays / région)",
      profile: "Profil de torréfaction utilisé",
      espresso: "Espresso",
      omni: "Omni",
      filtre: "Filtre",
      collab: "Prêt à tester notre café ?",
      yes: "Oui",
      maybe: "Peut-être",
      no: "Non",
      contactPref: "Mode de contact préféré",
      contactTel: "Téléphone",
      contactMail: "Email",
      contactWA: "WhatsApp",
      contactVisit: "Visite en personne",
      submit: "Envoyer"
    }
  }
};

function Input({ label, name, required = false, type = "text" }) {
  return (
    <label className="block mb-4 text-sm text-neutral-800">
      {label}
      <input
        type={type}
        name={name}
        required={required}
        className="mt-0.5 w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm outline-none ring-0 transition placeholder:text-neutral-400"
      />
    </label>
  );
}

function RadioGroup({ name, options }) {
  return (
    <div className="flex flex-col gap-1 mb-4">
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

export default function App() {
  const [lang, setLang] = useState("fr");
  const tr = t[lang];

  return (
    <div className="min-h-screen bg-[#f5f5f5] px-3 py-6 md:px-10 md:py-10">
      <div className="mx-auto max-w-4xl rounded-[32px] bg-white shadow-md border border-neutral-200 px-5 py-6 md:px-10 md:py-8">
        <header className="mb-6 flex items-center justify-between">
          <div className="text-lg font-semibold tracking-[-0.35em]">
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

        <main>
          <h1 className="mb-2 text-2xl font-semibold tracking-tight md:text-3xl">
            {tr.hero}
          </h1>
          <p className="mb-6 text-sm text-neutral-700 md:text-[15px]">
            {tr.sub}
          </p>

          <form
            method="POST"
            action={FORMSPREE_ENDPOINT}
            className="grid grid-cols-1 gap-5 md:grid-cols-2"
          >
            <Input label={tr.form.company} name="company" required />
            <Input label={tr.form.contact} name="contact" required />
            <Input label={tr.form.email} name="email" required type="email" />
            <Input label={tr.form.phone} name="phone" required />
            <Input label={tr.form.address} name="address" required />
            <Input label={tr.form.volume} name="volume" required />
            <Input label={tr.form.priceTarget} name="priceTarget" required />
            <Input label={tr.form.currentRoaster} name="currentRoaster" />
            <Input label={tr.form.origin} name="origin" />

            <div>
              <p className="mb-1 text-sm font-medium text-neutral-800">
                {tr.form.profile}
              </p>
              <RadioGroup
                name="roastProfile"
                options={[tr.form.espresso, tr.form.omni, tr.form.filtre]}
              />
            </div>

            <div>
              <p className="mb-1 text-sm font-medium text-neutral-800">
                {tr.form.collab}
              </p>
              <RadioGroup
                name="collab"
                options={[tr.form.yes, tr.form.maybe, tr.form.no]}
              />
            </div>

            <div>
              <p className="mb-1 text-sm font-medium text-neutral-800">
                {tr.form.contactPref}
              </p>
              <RadioGroup
                name="contactPref"
                options={[tr.form.contactTel, tr.form.contactMail, tr.form.contactWA, tr.form.contactVisit]}
              />
            </div>

            <div className="md:col-span-2">
              <button
                type="submit"
                className="w-full rounded-xl bg-[#C58A44] px-4 py-3 text-center text-white transition hover:bg-[#b77d3c]"
              >
                {tr.form.submit}
              </button>
            </div>
          </form>

          <div className="mt-10 md:mt-12 grid gap-4 md:grid-cols-3 text-sm text-neutral-800">
            <div>
              <h2 className="mb-2 font-semibold">{tr.benefits}</h2>
              <ul className="list-disc list-inside">
                <li>{tr.b1}</li>
                <li>{tr.b2}</li>
                <li>{tr.b3}</li>
              </ul>
            </div>
            <div className="md:col-span-2">
              <h2 className="mb-2 font-semibold">{tr.conditions}</h2>
              <ul className="list-disc list-inside">
                {tr.conditionsList.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
