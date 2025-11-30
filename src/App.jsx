import React, { useMemo, useState } from "react";

const FORMSPREE_ENDPOINT = "https://formspree.io/f/mrbonpno";

const t = {
  fr: {
    lang: "FR",
    switchTo: "EN",
    hero: "Lot d’essai pour HoReCa",
    sub: "Torréfaction de spécialité pour cafés et restaurants à Paris.",
    benefits: "Pourquoi nous ?",
    b1: "Qualité stable, profils clairs",
    b2: "Prix B2B transparents",
    b3: "Livraison rapide sur Paris",
    assortment: "Assortiment",
    assortmentText:
      "Espresso & filtre : Brésil, Colombie, Éthiopie, Honduras, Kenya, Pérou, Burundi, Salvador, Rwanda. Profil HoReCa.",
    terms: "Conditions",
    termsList: [
      "Volumes d’essai flexibles (lot pilote HoReCa).",
      "Contrats B2B simples, facturation mensuelle.",
      "Livraison sur Paris intra-muros sous 24–72 h."
    ],
    // правый блок
    rightLead: "Si l’échantillon vous plaît, laissez une demande d’achat.",
    rightTitle: "Comment est composé le lot ?",
    rightList: [
      "Trois paquets d’essai de 250 g (origines/terroirs variés), profils espresso.",
      "Torréfaction la semaine de l’envoi ; chaque lot avec profil et date.",
      "Retour d’expérience : ce qui a plu / moins plu — on fixe le profil pour les livraisons régulières."
    ],
    // форма
    form: {
      title: "Laissez votre demande",
      company: "Société",
      contact: "Personne de contact",
      email: "E-mail",
      address: "Adresse",
      phone: "Téléphone",
      volume: "Volume mensuel attendu (kg)",
      targetPrice: "Prix souhaité / kg (€)",
      comment: "Commentaire",
      submit: "Envoyer la demande",
      ok: "Merci ! Votre demande a été envoyée.",
      // блоки
      generalTitle: "1. Informations générales",
      // блок 2 — текущий кофе
      currentCoffeeTitle: "2. Informations sur votre café actuel",
      currentSupplier: "Torréfacteur / marque actuelle",
      currentOrigin: "Pays / région utilisés d’habitude",
      currentProfile: "Profil de torréfaction actuel (espresso / omni / filtre)",
      // блок 3 — цены
      priceBlockTitle: "3. Bloc prix",
      priceQ1:
        "À quel prix achetez-vous habituellement 1 kg de café de spécialité ?",
      priceQ1Options: [
        "Jusqu’à 22 €/kg",
        "22–24 €/kg",
        "24–26 €/kg",
        "26–28 €/kg",
        "28+ €/kg"
      ],
      priceQ2:
        "À quel prix êtes-vous prêt à acheter un café de spécialité 83+ pts (qualité stable) ?",
      priceQ2Options: ["≤ 23 €/kg", "23–25 €/kg", "25–27 €/kg", "27–29 €/kg"],
      priceQ2Individual: "À discuter individuellement",
      priceQ3:
        "Quel prix est trop élevé pour que l’achat soit impossible ?",
      priceQ3Options: ["24 €/kg", "26 €/kg", "28 €/kg", "30 €/kg"],
      // блок 4 — объём
      volumeTitle: "4. Volume mensuel",
      volumeQuestion: "Combien de kilos de café achetez-vous par mois ?",
      volumeOptions: [
        "Jusqu’à 10 kg",
        "10–20 kg",
        "20–35 kg",
        "35–50 kg",
        "50–100 kg",
        "100+ kg"
      ],
      // блок 5 — готовность к сотрудничеству
      cooperationTitle: "5. Disponibilité à coopérer",
      cooperationReadyLabel: "Prêt à tester notre café",
      cooperationReadyOptions: ["Oui", "Peut-être", "Non"],
      preferredContactLabel: "Mode de contact préféré",
      preferredContactOptions: ["Téléphone", "E-mail", "WhatsApp", "Visite"],
      selectPlaceholder: "Choisir une option"
    },
    footer: "© 2025 NÉORA — Paris"
  },

  en: {
    lang: "EN",
    switchTo: "FR",
    hero: "Trial batch for HoReCa",
    sub: "Specialty roasting for cafés & restaurants in Paris.",
    benefits: "Why us?",
    b1: "Consistent quality & clear profiles",
    b2: "Transparent B2B pricing",
    b3: "Fast delivery in Paris",
    assortment: "Assortment",
    assortmentText:
      "Espresso & filter: Brazil, Colombia, Ethiopia, Honduras, Kenya, Peru, Burundi, El Salvador, Rwanda. HoReCa-tuned.",
    terms: "Terms",
    termsList: [
      "Flexible pilot volumes (HoReCa trial).",
      "Simple B2B contracts, monthly invoicing.",
      "Paris delivery within 24–72 h."
    ],
    rightLead: "If you liked the tasting set, leave a purchase request.",
    rightTitle: "What’s inside the set?",
    rightList: [
      "Three 250 g trial bags (different origins/terroirs), espresso profiles.",
      "Roasted the week of dispatch; each lot with profile and roast date.",
      "Feedback on what you liked / didn’t — we lock the profile for regular supply."
    ],
    form: {
      title: "Leave a request",
      company: "Company",
      contact: "Contact person",
      email: "E-mail",
      address: "Address",
      phone: "Phone",
      volume: "Expected monthly volume (kg)",
      targetPrice: "Desired price / kg (€)",
      comment: "Comment",
      submit: "Send request",
      ok: "Thanks! Your request has been sent.",
      // blocks
      generalTitle: "1. General information",
      // block 2 — current coffee
      currentCoffeeTitle: "2. Current coffee details",
      currentSupplier: "Current supplier / roaster (brand)",
      currentOrigin: "Country / region you usually use",
      currentProfile: "Roast profile (espresso / omni / filter)",
      // block 3 — pricing
      priceBlockTitle: "3. Pricing block",
      priceQ1:
        "At what price do you usually buy 1 kg of specialty coffee?",
      priceQ1Options: [
        "Up to €22/kg",
        "€22–24/kg",
        "€24–26/kg",
        "€26–28/kg",
        "€28+/kg"
      ],
      priceQ2:
        "At what price are you ready to buy 83+ pts specialty coffee (stable quality)?",
      priceQ2Options: ["≤ €23/kg", "€23–25/kg", "€25–27/kg", "€27–29/kg"],
      priceQ2Individual: "Consider individually",
      priceQ3:
        "At what price is the coffee too expensive for you to buy?",
      priceQ3Options: ["€24/kg", "€26/kg", "€28/kg", "€30/kg"],
      // block 4 — volume
      volumeTitle: "4. Monthly volume",
      volumeQuestion: "How many kilograms of coffee do you buy per month?",
      volumeOptions: [
        "Up to 10 kg",
        "10–20 kg",
        "20–35 kg",
        "35–50 kg",
        "50–100 kg",
        "100+ kg"
      ],
      // block 5 — cooperation
      cooperationTitle: "5. Willingness to cooperate",
      cooperationReadyLabel: "Ready to test our coffee",
      cooperationReadyOptions: ["Yes", "Maybe", "No"],
      preferredContactLabel: "Preferred way of contact",
      preferredContactOptions: ["Phone", "E-mail", "WhatsApp", "In-person visit"],
      selectPlaceholder: "Select an option"
    },
    footer: "© 2025 NÉORA — Paris"
  },

  ru: {
    lang: "RU",
    switchTo: "FR",
    hero: "Пробная партия для HoReCa",
    sub: "Спешиалти-обжарка для кофеен и ресторанов в Париже.",
    benefits: "Почему мы?",
    b1: "Стабильное качество, ясные профили",
    b2: "Прозрачные B2B-цены",
    b3: "Быстрая доставка по Парижу",
    assortment: "Ассортимент",
    assortmentText:
      "Эспрессо и фильтр: Бразилия, Колумбия, Эфиопия, Гондурас, Кения, Перу, Бурунди, Сальвадор, Руанда. Профиль HoReCa.",
    terms: "Условия",
    termsList: [
      "Гибкие тестовые объёмы (пилот для HoReCa).",
      "Простые B2B-договоры, помесячная отчётность.",
      "Доставка по Парижу 24–72 ч."
    ],
    rightLead:
      "Если дегустационный набор понравился — оставьте заявку на закупку.",
    rightTitle: "Как устроена партия?",
    rightList: [
      "Три пробные упаковки по 250 г (разные регионы/терруары), профили под эспрессо.",
      "Обжарка в неделю отгрузки; у каждого лота есть профиль и дата.",
      "Обратная связь: что понравилось/не понравилось — закрепим профиль для регулярных поставок."
    ],
    form: {
      title: "Оставить заявку",
      company: "Компания",
      contact: "Контактное лицо",
      email: "E-mail",
      address: "Адрес",
      phone: "Телефон",
      volume: "Ожидаемый объём в месяц (кг)",
      targetPrice: "Желаемая цена / кг (€)",
      comment: "Комментарий",
      submit: "Отправить заявку",
      ok: "Спасибо! Ваша заявка отправлена.",
      // блоки
      generalTitle: "1. Общая информация",
      // блок 2 — текущий кофе
      currentCoffeeTitle: "2. Сведения о текущем кофе",
      currentSupplier: "Текущий поставщик (бренд / обжарщик)",
      currentOrigin: "Страна / регион, который вы обычно используете",
      currentProfile: "Профиль обжарки (espresso / omni / filtre)",
      // блок 3 — ценовой
      priceBlockTitle: "3. Ценовой блок",
      priceQ1:
        "По какой цене вы обычно закупаете 1 кг спешлти-кофе?",
      priceQ1Options: [
        "До 22 €/кг",
        "22–24 €/кг",
        "24–26 €/кг",
        "26–28 €/кг",
        "28+ €/кг"
      ],
      priceQ2:
        "По какой цене вы готовы закупать спешлти-кофе 83+ pts (стабильное качество)?",
      priceQ2Options: ["≤ 23 €/кг", "23–25 €/кг", "25–27 €/кг", "27–29 €/кг"],
      priceQ2Individual: "Рассматриваю индивидуально",
      priceQ3:
        "Какая цена является для вас слишком высокой, при которой закупка невозможна?",
      priceQ3Options: ["24 €/кг", "26 €/кг", "28 €/кг", "30 €/кг"],
      // блок 4 — объём
      volumeTitle: "4. Месячный объём",
      volumeQuestion: "Сколько килограммов кофе вы закупаете в месяц?",
      volumeOptions: [
        "До 10 кг",
        "10–20 кг",
        "20–35 кг",
        "35–50 кг",
        "50–100 кг",
        "100+ кг"
      ],
      // блок 5 — сотрудничество
      cooperationTitle: "5. Готовность к сотрудничеству",
      cooperationReadyLabel: "Готов протестировать наш кофе",
      cooperationReadyOptions: ["Да", "Возможно", "Нет"],
      preferredContactLabel: "Желаемый способ связи",
      preferredContactOptions: ["Телефон", "E-mail", "WhatsApp", "Личный визит"],
      selectPlaceholder: "Выберите вариант"
    },
    footer: "© 2025 NÉORA — Париж"
  }
};

export default function App() {
  const [lang, setLang] = useState("fr");
  const [ok, setOk] = useState(false);
  const [sending, setSending] = useState(false);
  const L = t[lang];

  const pageUrl = useMemo(
    () => (typeof window !== "undefined" ? window.location.href : ""),
    []
  );
  const nextLang = (l) => (l === "fr" ? "en" : l === "en" ? "ru" : "fr");

  async function onSubmit(e) {
    e.preventDefault();
    if (sending) return;
    setSending(true);
    try {
      const form = e.currentTarget;
      const data = Object.fromEntries(new FormData(form).entries());
      const payload = {
        ...data,
        _subject: "NÉORA — HoReCa lead",
        lang,
        page: pageUrl
      };

      const resp = await fetch(FORMSPREE_ENDPOINT, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json"
        },
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
      {/* Header */}
      <header className="header">
        <div className="container header-inner">
          <div className="brand">
            N<span className="accent">É</span>ORA
          </div>
          <button
            className="lang-btn"
            onClick={() => setLang(nextLang(lang))}
            title={L.switchTo}
          >
            {L.lang}
          </button>
        </div>
      </header>

      <main className="container">
        {/* Hero grid */}
        <section className="section grid">
          {/* Left: form */}
          <div>
            <h1 className="h1">{L.hero}</h1>
            <p className="sub">{L.sub}</p>

            <form className="form" onSubmit={onSubmit}>
              <input type="hidden" name="_subject" value="NÉORA — HoReCa lead" />
              <input type="hidden" name="lang" value={lang} />
              <input type="hidden" name="page" value={pageUrl} />

              {/* 1. Общая информация */}
              <p
                className="p"
                style={{ marginTop: 16, marginBottom: 4, fontWeight: 600 }}
              >
                {L.form.generalTitle}
              </p>

              <input
                className="input"
                name="company"
                required
                placeholder={L.form.company}
              />
              <input
                className="input"
                name="contact"
                required
                placeholder={L.form.contact}
              />
              <input
                className="input"
                type="email"
                name="email"
                required
                placeholder={L.form.email}
              />
              <input
                className="input"
                name="address"
                placeholder={L.form.address}
              />
              <input className="input" name="phone" placeholder={L.form.phone} />

              {/* 2. Сведения о текущем кофе */}
              <p
                className="p"
                style={{ marginTop: 16, marginBottom: 4, fontWeight: 600 }}
              >
                {L.form.currentCoffeeTitle}
              </p>
              <input
                className="input"
                name="currentSupplier"
                placeholder={L.form.currentSupplier}
              />
              <input
                className="input"
                name="currentOrigin"
                placeholder={L.form.currentOrigin}
              />
              <input
                className="input"
                name="currentProfile"
                placeholder={L.form.currentProfile}
              />

              {/* 3. Ценовой блок */}
              <p
                className="p"
                style={{ marginTop: 16, marginBottom: 4, fontWeight: 600 }}
              >
                {L.form.priceBlockTitle}
              </p>

              {/* Вопрос 1 */}
              <p className="p" style={{ margin: "6px 0" }}>
                {L.form.priceQ1}
              </p>
              <select className="input" name="priceCurrent" defaultValue="">
                <option value="" disabled>
                  {L.form.selectPlaceholder}
                </option>
                {L.form.priceQ1Options.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>

              {/* Вопрос 2 */}
              <p className="p" style={{ margin: "10px 0 6px" }}>
                {L.form.priceQ2}
              </p>
              <select className="input" name="priceReady" defaultValue="">
                <option value="" disabled>
                  {L.form.selectPlaceholder}
                </option>
                {L.form.priceQ2Options.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
              <label
                className="p"
                style={{
                  display: "flex",
                  alignItems: "center",
                  fontSize: 12,
                  marginTop: 4
                }}
              >
                <input
                  type="checkbox"
                  name="priceReadyIndividual"
                  style={{ marginRight: 6 }}
                />
                {L.form.priceQ2Individual}
              </label>

              {/* Вопрос 3 */}
              <p className="p" style={{ margin: "10px 0 6px" }}>
                {L.form.priceQ3}
              </p>
              <select className="input" name="priceTooHigh" defaultValue="">
                <option value="" disabled>
                  {L.form.selectPlaceholder}
                </option>
                {L.form.priceQ3Options.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>

              {/* 4. Месячный объём */}
              <p
                className="p"
                style={{ marginTop: 16, marginBottom: 4, fontWeight: 600 }}
              >
                {L.form.volumeTitle}
              </p>
              <p className="p" style={{ margin: "0 0 6px" }}>
                {L.form.volumeQuestion}
              </p>
              <select className="input" name="monthlyVolume" defaultValue="">
                <option value="" disabled>
                  {L.form.selectPlaceholder}
                </option>
                {L.form.volumeOptions.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>

              {/* 5. Готовность к сотрудничеству */}
              <p
                className="p"
                style={{ marginTop: 16, marginBottom: 4, fontWeight: 600 }}
              >
                {L.form.cooperationTitle}
              </p>
              <p className="p" style={{ margin: "0 0 6px" }}>
                {L.form.cooperationReadyLabel}
              </p>
              <select className="input" name="readyToTest" defaultValue="">
                <option value="" disabled>
                  {L.form.selectPlaceholder}
                </option>
                {L.form.cooperationReadyOptions.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>

              <p className="p" style={{ margin: "10px 0 6px" }}>
                {L.form.preferredContactLabel}
              </p>
              <select
                className="input"
                name="preferredContact"
                defaultValue=""
              >
                <option value="" disabled>
                  {L.form.selectPlaceholder}
                </option>
                {L.form.preferredContactOptions.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>

              {/* Комментарий */}
              <textarea
                className="textarea"
                name="comment"
                placeholder={L.form.comment}
              />

              <button className="btn" disabled={sending}>
                {sending ? "…" : L.form.submit}
              </button>

              {ok && <p className="ok">{L.form.ok}</p>}
            </form>
          </div>

          {/* Right: info card */}
          <div className="card">
            <p className="p" style={{ marginTop: 0 }}>
              {L.rightLead}
            </p>
            <h3 className="h2" style={{ fontSize: 16, marginTop: 10 }}>
              {L.rightTitle}
            </h3>
            <ul className="ul">
              {L.rightList.map((x, i) => (
                <li className="li" key={i}>
                  {x}
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Benefits */}
        <section className="section">
          <h2 className="h2">{L.benefits}</h2>
          <div className="cards">
            <div className="card">{L.b1}</div>
            <div className="card">{L.b2}</div>
            <div className="card">{L.b3}</div>
          </div>
        </section>

        {/* Assortment */}
        <section className="section">
          <h2 className="h2">{L.assortment}</h2>
          <p className="p">{L.assortmentText}</p>
        </section>

        {/* Terms */}
        <section className="section">
          <h2 className="h2">{L.terms}</h2>
          <ul className="ul">
            {L.termsList.map((x, i) => (
              <li className="li" key={i}>
                {x}
              </li>
            ))}
          </ul>
        </section>
      </main>

      <footer className="footer">{L.footer}</footer>
    </>
  );
}
