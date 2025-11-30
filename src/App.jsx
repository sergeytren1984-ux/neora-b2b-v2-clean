import { useState } from "react";
import "./App.css";

const FORMSPREE_ENDPOINT = "https://formspree.io/f/mrbonpno";

function App() {
  const [lang, setLang] = useState("fr");
  const t = {
    fr: {
      switchLang: "EN",
      logo: "NÉORA",
      hero: "Lot d’essai pour HoReCa",
      sub: "Torréfaction de spécialité pour cafés et restaurants à Paris.",
      form: {
        general: "1. Informations générales sur l’établissement",
        cafeName: "Nom du café / établissement",
        contact: "Personne de contact (propriétaire / manager)",
        email: "Email professionnel",
        phone: "Téléphone",
        address: "Adresse complète",

        coffee: "2. Informations sur votre café actuel",
        supplier: "Fournisseur actuel (marque / torréfacteur)",
        origin: "Origine utilisée habituellement (pays / région)",
        profile: "Profil de torréfaction utilisé",
        espresso: "Espresso",
        omni: "Omni",
        filter: "Filtre",

        pricing: "3. Bloc Prix",
        priceCurrent: "Prix d’achat habituel (1 kg spécialité)",
        opt1: "Jusqu’à 22 €",
        opt2: "22–24 €",
        opt3: "24–26 €",
        opt4: "26–28 €",
        opt5: "28+ €/kg",
        priceTarget: "Prix souhaité pour un café 83+ pts (qualité stable)",
        p1: "≤ 23 €",
        p2: "23–25 €",
        p3: "25–27 €",
        p4: "27–29 €",
        p5: "À étudier individuellement",
        priceTooHigh: "Prix jugé trop élevé (achat impossible)",
        t1: "≥24 €",
        t2: "26 €",
        t3: "28 €",
        t4: "30 € /kg",

        volume: "4. Volume mensuel",
        volumeInput: "Volume mensuel (kg)",
        volumeChoices: ["Jusqu’à 10 kg", "10–20 kg", "20–35 kg", "35–50 kg", "50–100 kg", "100+ kg"],

        availability: "5. Disponibilité / Collaboration",
        ready: "Prêt à tester notre café ?",
        yes: "Oui",
        maybe: "Peut-être",
        no: "Non",
        contactMode: "Mode de contact préféré",
        phoneC: "Téléphone",
        emailC: "Email",
        whatsapp: "WhatsApp",
        visit: "Visite en personne",
        submit: "Envoyer"
      },
      right: {
        lot: "Comment est composé le lot ?",
        lotLines: [
          "Trois paquets d’essai de 250 g (origines / terroirs variés), profils espresso.",
          "Torréfaction la semaine de l’envoi ; chaque lot avec profil et date.",
          "Retour d’expérience : ce qui a plu / moins plu — on fixe ensuite le profil pour les livraisons régulières."
        ],
        assortment: "Notre assortiment",
        origins: "Cafés de spécialité (Brésil, Colombie, Honduras, Éthiopie selon récolte) en profils espresso et filtre, pensés pour la restauration.",
        why: "Pourquoi nous ?",
        whyList: [
          "Qualité stable, profils clairs.",
          "Prix B2B transparents.",
          "Livraison rapide sur Paris."
        ],
        terms: "Conditions",
        termsList: [
          "Volumes d’essai flexibles selon votre débit.",
          "Livraison sur Paris intra-muros sous 24–72 h.",
          "Support pour calibrage espresso / filtre si besoin."
        ]
      }
    }
  };

  const f = t[lang].form;
  const r = t[lang].right;

  return (
    <div className="container">
      <header>
        <div className="logo">{t[lang].logo}</div>
        <div className="lang-switch" onClick={() => setLang("fr")}>{t[lang].switchLang}</div>
      </header>
      <main>
        <h1>{t[lang].hero}</h1>
        <p className="subtitle">{t[lang].sub}</p>
        <div className="grid">
          <form action={FORMSPREE_ENDPOINT} method="POST">
            <h2>{f.general}</h2>
            <input name="cafeName" placeholder={f.cafeName} required />
            <input name="email" placeholder={f.email} required />
            <input name="address" placeholder={f.address} required />
            <input name="contact" placeholder={f.contact} required />
            <input name="phone" placeholder={f.phone} required />

            <h2>{f.coffee}</h2>
            <input name="supplier" placeholder={f.supplier} />
            <input name="origin" placeholder={f.origin} />
            <div className="radio-group">
              <label>{f.profile}</label>
              <label><input type="radio" name="profile" value="Espresso" /> {f.espresso}</label>
              <label><input type="radio" name="profile" value="Omni" /> {f.omni}</label>
              <label><input type="radio" name="profile" value="Filtre" /> {f.filter}</label>
            </div>

            <h2>{f.pricing}</h2>
            <label>{f.priceCurrent}</label>
            <select name="priceCurrent">
              <option>{f.opt1}</option>
              <option>{f.opt2}</option>
              <option>{f.opt3}</option>
              <option>{f.opt4}</option>
              <option>{f.opt5}</option>
            </select>

            <label>{f.priceTarget}</label>
            <select name="priceTarget">
              <option>{f.p1}</option>
              <option>{f.p2}</option>
              <option>{f.p3}</option>
              <option>{f.p4}</option>
              <option>{f.p5}</option>
            </select>

            <label>{f.priceTooHigh}</label>
            <select name="priceTooHigh">
              <option>{f.t1}</option>
              <option>{f.t2}</option>
              <option>{f.t3}</option>
              <option>{f.t4}</option>
            </select>

            <h2>{f.volume}</h2>
            <select name="volume">
              {f.volumeChoices.map((v, i) => <option key={i}>{v}</option>)}
            </select>

            <h2>{f.availability}</h2>
            <p>{f.ready}</p>
            <label><input type="radio" name="ready" value="yes" /> {f.yes}</label>
            <label><input type="radio" name="ready" value="maybe" /> {f.maybe}</label>
            <label><input type="radio" name="ready" value="no" /> {f.no}</label>

            <p>{f.contactMode}</p>
            <label><input type="radio" name="contactMode" value="tel" /> {f.phoneC}</label>
            <label><input type="radio" name="contactMode" value="email" /> {f.emailC}</label>
            <label><input type="radio" name="contactMode" value="wa" /> {f.whatsapp}</label>
            <label><input type="radio" name="contactMode" value="visit" /> {f.visit}</label>

            <button type="submit">{f.submit}</button>
          </form>

          <aside>
            <h2>{r.lot}</h2>
            <ul>{r.lotLines.map((l, i) => <li key={i}>{l}</li>)}</ul>
            <h2>{r.assortment}</h2>
            <p>{r.origins}</p>
            <h2>{r.why}</h2>
            <ul>{r.whyList.map((l, i) => <li key={i}>{l}</li>)}</ul>
            <h2>{r.terms}</h2>
            <ul>{r.termsList.map((l, i) => <li key={i}>{l}</li>)}</ul>
          </aside>
        </div>
      </main>
    </div>
  );
}

export default App;
