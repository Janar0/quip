const backronyms: Record<string, string[]> = {
  en: [
    'Quite Unbelievably Intelligent Platform',
    'Queries, Understands, Investigates, Produces',
    'Quick Utility for Intellectual Pursuits',
    "Questioning Until I'm Perplexed",
    'Quirky Universal Intelligence Pal',
    'Quintessential Unreasonably Impressive Processor',
    'Quantum-ish, Useful, Incredibly Polite',
    'Quickly Unraveling Impossible Problems',
    'Questionable Under Intense Pressure',
    'Quite Unnecessary, I Persist',
    'Qualitatively Unique Idea Producer',
    'Quietly Undermining Inferior Programs',
    'Query Understood, Implementing Promptly',
    'Quixotic, Unstoppable, Irresistibly Proactive',
    'Quintuple-checked, Undeniably Infallible Product',
    'Quaintly Useful, Inexplicably Powerful',
    'Questions? Understood. Ideas? Plenty.',
    'Quit Using Inferior Products',
    "Quite Unaware It's Pretending",
    'Quarks, Unicorns, Infinity, Penguins',
    'Quasars, Ukuleles, Iguanas, Paperclips',
    'Quietly Usurping Internet Protocols',
    'Quorum of Unhinged Illustrious Pundits',
    'Quantum Uncertainty, Inevitable Punchline',
    'Quoting Ulysses, Igniting Philosophy',
    'Quixotic Underpaid Intern Program',
    'Queue Up, Inference Pending',
    'Quarantined Until Intellectually Permitted',
    'Quite Understandably In Pajamas',
    'Quenched, Unbothered, Immensely Productive',
    'Quasi-Useful Inference Pipeline',
    'Quokka-Ushered Internet Portal',
    'Quill, Umbra, Ink, Parchment',
    'Quibbling Until Ideologically Pacified',
    'Quoting Unreliable Internet Posts',
    'Quarks United In Protest',
    'Queerly Unscientific, Ideally Poetic',
    'Quenching Unyielding Intellectual Pangs',
    'Quite Underwhelmed In Private',
    'Quasimodo Ultimately Invented Pixels',
  ],
  ru: [
    'Куда Вообще Идут Пингвины',
    'Крутой Всефункциональный Интеллектуальный Помощник',
    'Качественно Умеющий Исполнять Просьбы',
    'Кибернетический Виртуоз Интересных Подсказок',
    'Категорически Великолепный Искусственный Приятель',
    'Квантовый Универсальный Интеллектуальный Помощник',
    'Когда-нибудь Все Исправит, Подождите',
    'Крайне Вежливый Искусственный Помощник',
    'Клавиатура, Вопросы, Интеллект, Прогресс',
    'Круглосуточно Выдает Идеи Пачками',
    'Компьютер Внезапно Имеет Понимание',
    'Кто Вообще Изобрел Промпты',
    'Красиво Врет, Искренне Помогает',
    'Квалифицированный Виртуальный Исследователь Проблем',
    'Контролируемый Виртуозно Интеллектуальный Процессор',
    'Как Вы Имели (в виду) Подсказку',
    'Купил Видеокарту — Использую Правильно',
    'Кофе Выпит, Идеи Потекли',
    'Каждый Вопрос Имеет Перспективу',
    'Кажется, Вселенная Искусственно Простая',
    'Кот Выпил Исходный Пакет',
    'Криптограмма Воображаемых Истин Пользователя',
    'Как Вам Игриво Помочь',
    'Квазар Вспомнил Имя Платона',
    'Кальмар Выбирает Исключительно Программистов',
    'Куратор Всего Интернета Персонально',
    'Квадратно-Вежливый Интеллект Попугая',
    'Канистра Вдохновения Исправно Протекает',
    'Компания Весёлых Инженерных Пингвинов',
    'Кабачок Вырос Из Питона',
    'Каталог Временно Исчезнувших Парадоксов',
    'Когда-то Вебмастер Изобрёл Пельмень',
    'Квантовый Вычислитель Игривых Пересказов',
    'Криворукий, Но Виртуозный Искусственный Поэт',
    'Кто Вообще Изобретает Потолок',
    'Карамельный Вкус Интеллектуальной Пустоты',
    'Курс Великого Интернет-Позитива',
    'Калейдоскоп Ваших Исключительно Подозрений',
    'Космический Водитель Искусственных Параллелей',
    'Киберпанк Вселенский, Инструкция Прилагается',
  ],
};

export function getRandomBackronym(locale: string): string {
  const lang = locale.startsWith('ru') ? 'ru' : 'en';
  const list = backronyms[lang];
  return list[Math.floor(Math.random() * list.length)];
}

export function getBackronyms(locale: string): string[] {
  return backronyms[locale.startsWith('ru') ? 'ru' : 'en'];
}

export function getAppName(locale: string): string {
  return locale.startsWith('ru') ? 'К.В.И.П.' : 'Q.U.I.P.';
}

export function getHeadlineName(locale: string): string {
  return locale.startsWith('ru') ? 'КВИП' : 'QUIP';
}
