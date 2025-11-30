// App.jsx — финальная версия по ТЗ от старого сайта

import "./App.css";
import { useState } from "react";

const FORMSPREE_ENDPOINT = "https://formspree.io/f/mrbonpno";

function App() {
  const [lang, setLang] = useState("fr");

  const t = {
    fr: {
      lang: "FR",
      switchTo: "EN",
      title: "Lot d’essai pour HoReCa",
      sub: "Torréfaction de spécialité pour cafés et restaurants à Paris.",
      form: {
        name: "Nom du café / établissement",
        email: "Email professionnel",
        address: "Adresse complète",
        contact: "Personne de contact",
        phone: "Téléphone",
        volume: "Volume mensuel (kg)",
        roaster: "Fournisseur actuel (marque / torréfacteur)",
        origin: "Origine utilisée habituellement (pays / région)",
        price: "Prix cible pour 1 kg café spécialité (83+ pts)",
        profile: "Profil de torréfaction utilisé",
        profileOptions: ["Espresso", "Omni", "Filtre"],
        ready: "Prêt à tester notre café ?",
        readyOptions: ["Oui", "Peut-être", "Non"],
        contactMode: "Mode de contact préféré",
        contactOptions: ["Téléphone", "Email", "WhatsApp", "Visite en personne"],
        submit: "Envoyer",
      },
      why: "Pourquoi nous ?",
      reasons: [
        "Qualité stable, profils clairs",
        "Prix B2B transparents",
        "Livraison rapide sur Paris"
      ],
      conditions: "Conditions",
      conds: [
        "Volumes d’essai flexibles selon votre débit.",
        "Livraison sur Paris intra-muros sous 24–72 h.",
        "Support pour calibrage espresso / filtre si besoin."
      ]
    }
  };

  const l = t[lang];
  const f = l.form;

  return (
    <div className="wrapper">
      <header>
        <div className="logo">N<span className="gold">É</span>ORA</div>
        <div className="lang" onClick={() => setLang("fr")}>{l.lang} · {l.switchTo}</div>
      </header>

      <h1>{l.title}</h1>
      <p className="sub">{l.sub}</p>

      <form action={FORMSPREE_ENDPOINT} method="POST">
        <div className="grid">
          <input required name="name" placeholder={f.name} />
          <input required name="contact" placeholder={f.contact} />
          <input required name="email" placeholder={f.email} />
          <input required name="phone" placeholder={f.phone} />
          <input required name="address" placeholder={f.address} />
          <input required name="volume" placeholder={f.volume} />
          <input required name="roaster" placeholder={f.roaster} />
          <input required name="origin" placeholder={f.origin} />
          <input required name="price" placeholder={f.price} />
        </div>

        <div className="block">
          <label>{f.profile}</label>
          {f.profileOptions.map((opt, i) => (
            <label key={i}><input type="radio" name="profile" value={opt} />{opt}</label>
          ))}
        </div>

        <div className="block">
          <label>{f.ready}</label>
          {f.readyOptions.map((opt, i) => (
            <label key={i}><input type="radio" name="ready" value={opt} />{opt}</label>
          ))}
        </div>

        <div className="block">
          <label>{f.contactMode}</label>
          {f.contactOptions.map((opt, i) => (
            <label key={i}><input type="radio" name="contactMode" value={opt} />{opt}</label>
          ))}
        </div>

        <button type="submit">{f.submit}</button>
      </form>

      <section className="side">
        <h2>{l.why}</h2>
        <ul>{l.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>

        <h2>{l.conditions}</h2>
        <ul>{l.conds.map((c, i) => <li key={i}>{c}</li>)}</ul>
      </section>
    </div>
  );
}

export default App;
