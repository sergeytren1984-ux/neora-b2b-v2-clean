import React, { useMemo, useState } from "react";

const FORMSPREE_ENDPOINT = "https://formspree.io/f/mrbonpno";

const t = {
  fr: {
    lang: "FR", switchTo: "EN",
    hero: "Lot d’essai pour HoReCa",
    sub: "Torréfaction de spécialité pour cafés et restaurants à Paris.",
    benefits: "Pourquoi nous ?",
    b1: "Qualité stable, profils clairs",
    b2: "Prix B2B transparents",
    b3: "Livraison rapide sur Paris",
    assortment: "Assortiment",
    assortmentText: "Espresso & filtre : Brésil, Colombie, Éthiopie, Honduras (selon récolte). Profil HoReCa.",
    terms: "Conditions",
    termsList: [
      "Volumes d’essai flexibles (lot pilote HoReCa).",
      "Contrats B2B simples, facturation mensuelle.",
      "Livraison sur Paris intra-muros sous 24–72 h."
    ],
    form: {
      title: "Laissez votre demande",
      company: "Société",
      contact: "Personne de contact",
      email: "E-mail",
      address: "Adresse",
      phone: "Téléphone",
      volume: "Volume mensuel attendu (kg)",
      comment: "Commentaire",
      submit: "Envoyer la demande",
      ok: "Merci ! Votre demande a été envoyée."
    },
    footer: "© 2025 NÉORA — Paris · neora-b2b.app"
  },
  en: {
    lang: "EN", switchTo: "FR",
    hero: "Trial batch for HoReCa",
    sub: "Specialty roasting for cafés & restaurants in Paris.",
    benefits: "Why us?",
    b1: "Consistent quality & clear profiles",
    b2: "Transparent B2B pricing",
    b3: "Fast delivery in Paris",
    assortment: "Assortment",
    assortmentText: "Espresso & filter: Brazil, Colombia, Ethiopia, Honduras (by harvest). HoReCa-tuned.",
    terms: "Terms",
    termsList: [
      "Flexible pilot volumes (HoReCa trial).",
      "Simple B2B contracts, monthly invoicing.",
      "Paris delivery within 24–72 h."
    ],
    form: {
      title: "Leave a request",
      company: "Company",
      contact: "Contact person",
      email: "E-mail",
      address: "Address",
      phone: "Phone",
      volume: "Expected monthly volume (kg)",
      comment: "Comment",
      submit: "Send request",
      ok: "Thanks! Your request has been sent."
    },
    footer: "© 2025 NÉORA — Paris · neora-b2b.app"
  },
  ru: {
    lang: "RU", switchTo: "FR",
    hero: "Пробная партия для HoReCa",
    sub: "Спешиалти-обжарка для кофеен и ресторанов в Париже.",
    benefits: "Почему мы?",
    b1: "Стабильное качество, ясные профили",
    b2: "Прозрачные B2B-цены",
    b3: "Быстрая доставка по Парижу",
    assortment: "Ассортимент",
    assortmentText: "Эспрессо и фильтр: Бразилия, Колумбия, Эфиопия, Гондурас (по урожаю). Профиль HoReCa.",
    terms: "Условия",
    termsList: [
      "Гибкие тестовые объёмы (пилот для HoReCa).",
      "Простые B2B-договоры, помесячная отчётность.",
      "Доставка по Парижу 24–72 ч."
    ],
    form: {
      title: "Оставить заявку",
      company: "Компания",
      contact: "Контактное лицо",
      email: "E-mail",
      address: "Адрес",
      phone: "Телефон",
      volume: "Ожидаемый объём в месяц (кг)",
      comment: "Комментарий",
      submit: "Отправить заявку",
      ok: "Спасибо! Ваша заявка отправлена."
    },
    footer: "© 2025 NÉORA — Paris · neora-b2b.app"
  }
};

export default function App() {
  const [lang, setLang] = useState("fr");
  const [ok, setOk] = useState(false);
  const [sending, setSending] = useState(false);
  const L = t[lang];

  const pageUrl = useMemo(() => (typeof window !== "undefined" ? window.location.href : ""), []);
  const nextLang = (l) => (l === "fr" ? "en" : l === "en" ? "ru" : "fr");

  async function onSubmit(e) {
    e.preventDefault();
    if (sending) return;
    setSending(true);
    try {
      const form = e.currentTarget;
      const data = Object.fromEntries(new FormData(form).entries());
      const payload = { ...data, _subject: "NÉORA — HoReCa lead", lang, page: pageUrl };

      const resp = await fetch(FORMSPREE_ENDPOINT, {
        method: "POST",
        headers: { "Accept": "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      if (resp.ok) {
        setOk(true);
        form.reset();
        setTimeout(() => setOk(false), 4500);
      } else {
        alert("Submit error. Try again or email hello@neora.coffee");
      }
    } catch {
      alert("Network error. Try again or email hello@neora.coffee");
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <header className="header">
        <div className="container header-inner">
          <div className="brand">
            N<span className="accent">É</span>ORA
          </div>
          <button className="lang-btn" onClick={() => setLang(nextLang(lang))} title={L.switchTo}>
            {L.lang}
          </button>
        </div>
      </header>

      <main className="container">
        <section className="section grid">
          {/* левая колонка — форма */}
          <div>
            <h1 className="h1">{L.hero}</h1>
            <p className="sub">{L.sub}</p>

            <form className="form" onSubmit={onSubmit}>
              <input type="hidden" name="_subject" value="NÉORA — HoReCa lead" />
              <input type="hidden" name="lang" value={lang} />
              <input type="hidden" name="page" value={pageUrl} />

              <input className="input" name="company" required placeholder={L.form.company} />
              <input className="input" name="contact" required placeholder={L.form.contact} />
              <input className="input" type="email" name="email" required placeholder={L.form.email} />
              <input className="input" name="address" placeholder={L.form.address} />
              <input className="input" name="phone" placeholder={L.form.phone} />
              <input className="input" name="monthlyVolume" placeholder={L.form.volume} />
              <textarea className="textarea" name="comment" placeholder={L.form.comment} />

              <button className="btn" disabled={sending}>
                {sending ? "…" : L.form.submit}
              </button>

              {ok && <p className="ok">{L.form.ok}</p>}
            </form>
          </div>

          {/* правая колонка — заглушка под мок */}
          <div className="card">
            <div className="mock">Image / pack mock (optional)</div>
          </div>
        </section>

        <section className="section">
          <h2 className="h2">{L.benefits}</h2>
          <div className="cards">
            <div className="card">{L.b1}</div>
            <div className="card">{L.b2}</div>
            <div className="card">{L.b3}</div>
          </div>
        </section>

        <section className="section">
          <h2 className="h2">{L.assortment}</h2>
          <p className="p">{L.assortmentText}</p>
        </section>

        <section className="section">
          <h2 className="h2">{L.terms}</h2>
          <ul className="ul">
            {L.termsList.map((x, i) => (
              <li className="li" key={i}>{x}</li>
            ))}
          </ul>
        </section>
      </main>

      <footer className="footer">{L.footer}</footer>
    </>
  );
}
