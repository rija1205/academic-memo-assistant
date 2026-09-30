'use strict';

/* --------------------------------------------------------------------------
   ThesisFlow — a local-first thesis writing workspace.
   The app deliberately works without a backend: projects are saved in the
   browser's localStorage and drafts are generated from transparent templates.
   -------------------------------------------------------------------------- */

const STORAGE_KEY = 'thesisflow-state-v1';

const SECTION_TYPES = {
  introduction: {
    label: 'Introduction',
    shortLabel: 'Introduction',
    guidance: 'Présentez le contexte, la problématique, les objectifs et l’annonce du plan.',
    tip: 'Terminez cette partie par une transition claire vers le chapitre suivant.',
    bullets: [
      'Contextualiser le sujet en 2 à 3 paragraphes',
      'Formuler la problématique et les questions de recherche',
      'Annoncer la méthode, le plan et les objectifs',
    ],
  },
  problematique: {
    label: 'Problématique',
    shortLabel: 'Problématique',
    guidance: 'Définissez le problème, son périmètre, ses enjeux et les hypothèses de travail.',
    tip: 'Une problématique claire tient généralement en une à trois phrases.',
    bullets: [
      'Délimiter le terrain et la population étudiée',
      'Distinguer le problème constaté du projet de recherche',
      'Présenter les hypothèses ou questions secondaires',
    ],
  },
  'cadre-theorique': {
    label: 'Cadre théorique',
    shortLabel: 'Cadre théorique',
    guidance: 'Présentez les concepts, les auteurs et les modèles mobilisés dans votre analyse.',
    tip: 'Ne listez pas les références : synthesizez ce qu’elles permettent d’éclairer.',
    bullets: [
      'Définir les concepts clés avec vos propres mots',
      'Comparer les approches théoriques retenues',
      'Faire le lien entre le cadre théorique et la problématique',
    ],
  },
  methodologie: {
    label: 'Méthodologie',
    shortLabel: 'Méthodologie',
    guidance: 'Expliquez votre démarche, les données, les outils et les limites de la méthode.',
    tip: 'Décrivez les procédures avec assez de détail pour qu’elles soient reproductibles.',
    bullets: [
      'Présenter le design de la recherche et l’échantillon',
      'Décrire les outils de collecte et d’analyse',
      'Ajouter les considérations éthiques et les limites',
    ],
  },
  resultats: {
    label: 'Résultats',
    shortLabel: 'Résultats',
    guidance: 'Organisez les résultats par thème et illustrez-les avec des tableaux ou graphiques.',
    tip: 'Décrivez d’abord les tendances, puis interprétez-les dans la partie suivante.',
    bullets: [
      'Créer une sous-section par résultat important',
      'Renvoyer aux tableaux, figures et indicateurs',
      'Distinguer les faits observés de votre interprétation',
    ],
  },
  discussion: {
    label: 'Discussion',
    shortLabel: 'Discussion',
    guidance: 'Interprétez les résultats, dialoguez avec la littérature et discutez les limites.',
    tip: 'Une bonne discussion répond à la problématique, pas seulement à la méthode.',
    bullets: [
      'Interpréter les résultats au regard du cadre théorique',
      'Comparer avec les études précédentes',
      'Discuter les limites et ouvrir des perspectives',
    ],
  },
  conclusion: {
    label: 'Conclusion générale',
    shortLabel: 'Conclusion',
    guidance: 'Répondez à la problématique, synthétisez les apports et formulez des perspectives.',
    tip: 'Ne copiez pas l’introduction : montrez ce que la recherche a permis de construire.',
    bullets: [
      'Répondre clairement à la problématique',
      'Synthétiser les principaux résultats et contributions',
      'Formuler les limites et les perspectives de recherche',
    ],
  },
  annexes: {
    label: 'Annexes',
    shortLabel: 'Annexes',
    guidance: 'Regroupez les questionnaires, grilles, tableaux et documents complémentaires.',
    tip: 'Numérotez chaque annexe et rappelez son lien dans le corps du mémoire.',
    bullets: [
      'Donner un titre et un numéro à chaque annexe',
      'Ajouter une courte notice de présentation',
      'Vérifier la lisibilité des documents scannés',
    ],
  },
  autre: {
    label: 'Autre partie',
    shortLabel: 'Autre',
    guidance: 'Structurez cette partie autour d’une idée directrice et d’un objectif précis.',
    tip: 'Un titre court et explicite aide le lecteur à suivre votre raisonnement.',
    bullets: [
      'Définir l’objectif de la partie',
      'Organiser les sous-sections de façon progressive',
      'Ajouter une transition vers la partie suivante',
    ],
  },
};

const DEFAULT_SECTION_BLUEPRINTS = [
  { title: 'Introduction générale', type: 'introduction' },
  { title: 'Revue de la littérature', type: 'cadre-theorique' },
  { title: 'Méthodologie', type: 'methodologie' },
  { title: 'Résultats', type: 'resultats' },
  { title: 'Discussion', type: 'discussion' },
  { title: 'Conclusion générale', type: 'conclusion' },
];

const ICON_PATHS = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.3"/><rect x="14" y="3" width="7" height="7" rx="1.3"/><rect x="3" y="14" width="7" height="7" rx="1.3"/><rect x="14" y="14" width="7" height="7" rx="1.3"/>',
  'book-open': '<path d="M2.8 5.1c2.3-.9 4.4-.6 6.2.8v13c-1.8-1.4-3.9-1.7-6.2-.8V5.1Z"/><path d="M21.2 5.1c-2.3-.9-4.4-.6-6.2.8v13c1.8-1.4 3.9-1.7 6.2-.8V5.1Z"/>',
  library: '<path d="M4 19.5h16"/><path d="M5.5 17V5.7a1.7 1.7 0 0 1 1.7-1.7h2.1A1.7 1.7 0 0 1 11 5.7V17"/><path d="M11 17V5.7a1.7 1.7 0 0 1 1.7-1.7h2.1a1.7 1.7 0 0 1 1.7 1.7V17"/><path d="M16.5 7.2h2.3a1.5 1.5 0 0 1 1.5 1.5v8.3h-3.8"/>',
  settings: '<path d="M12 15.1a3.1 3.1 0 1 0 0-6.2 3.1 3.1 0 0 0 0 6.2Z"/><path d="m19.4 15 .1.1a1.8 1.8 0 0 1-2.6 2.6l-.1-.1a1.8 1.8 0 0 0-3.1 1.3v.2a1.8 1.8 0 0 1-3.6 0v-.2a1.8 1.8 0 0 0-3.1-1.3l-.1.1a1.8 1.8 0 1 1-2.6-2.6l.1-.1A1.8 1.8 0 0 0 3.2 12a1.8 1.8 0 0 0-1.3-3.1h-.2a1.8 1.8 0 0 1 0-3.6h.2A1.8 1.8 0 0 0 3.2 2.2l-.1-.1a1.8 1.8 0 1 1 2.6-2.6l.1.1A1.8 1.8 0 0 0 9 0h.2a1.8 1.8 0 0 1 3.6 0v.2A1.8 1.8 0 0 0 16 1.5l.1-.1a1.8 1.8 0 1 1 2.6 2.6l-.1.1A1.8 1.8 0 0 0 19.9 7h.2a1.8 1.8 0 0 1 0 3.6h-.2a1.8 1.8 0 0 0-.5 4.4Z" transform="translate(0 4) scale(.67)"/>',
  'help-circle': '<circle cx="12" cy="12" r="9.2"/><path d="M9.7 9a2.5 2.5 0 1 1 4.1 1.9c-1 .8-1.8 1.2-1.8 2.5"/><path d="M12 16.7h.01"/>',
  'more-horizontal': '<circle cx="5" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1" fill="currentColor" stroke="none"/>',
  lightbulb: '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M8.3 14.8a6 6 0 1 1 7.4 0c-.9.7-1.2 1.3-1.2 2.2H9.5c0-.9-.3-1.5-1.2-2.2Z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  'arrow-right': '<path d="M5 12h14M13 6l6 6-6 6"/>',
  'file-text': '<path d="M14 2.8H6.8A1.8 1.8 0 0 0 5 4.6v14.8a1.8 1.8 0 0 0 1.8 1.8h10.4a1.8 1.8 0 0 0 1.8-1.8V7.4L14 2.8Z"/><path d="M14 3v4.5h5.2M8.5 12h7M8.5 15.5h7M8.5 19h4"/>',
  'pen-line': '<path d="m13.5 5.5 5 5M4 20l4.2-1 10.9-10.9a2.8 2.8 0 0 0-4-4L4.2 15 4 20Z"/><path d="M12 4 8 8"/>',
  check: '<path d="m5 12 4.2 4.2L19 6.5"/>',
  'check-circle': '<circle cx="12" cy="12" r="9"/><path d="m8 12 2.7 2.7L16.5 9"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/>',
  quote: '<path d="M9 11H5.8A2.8 2.8 0 0 0 3 13.8v.4A2.8 2.8 0 0 0 5.8 17H7a2 2 0 0 0 2-2v-4Zm12 0h-3.2a2.8 2.8 0 0 0-2.8 2.8v.4A2.8 2.8 0 0 0 18.8 17H20a2 2 0 0 0 2-2v-4Z"/>',
  'chevron-right': '<path d="m9 5 7 7-7 7"/>',
  'chevron-down': '<path d="m6 9 6 6 6-6"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4L16.5 3.5Z"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  copy: '<rect x="8" y="8" width="11" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h2"/>',
  sparkles: '<path d="m12 3-1.1 4.2L7 8.3l3.9 1.1L12 13.5l1.1-4.1L17 8.3l-3.9-1.1L12 3ZM19 13l-.7 2.3-2.3.7 2.3.7.7 2.3.7-2.3 2.3-.7-2.3-.7L19 13ZM5 14l-.6 1.9-1.9.6 1.9.6L5 19l.6-1.9 1.9-.6-1.9-.6L5 14Z"/>',
  'wand-sparkles': '<path d="m15 4 5 5M13 6l5 5M3 21l8.2-8.2M4.5 14.5l5 5M5 4v3M3.5 5.5h3M19 15v4M17 17h4"/>',
  bold: '<path d="M7 4h5.1a3.4 3.4 0 0 1 0 6.8H7V4Zm0 6.8h6.1a3.6 3.6 0 0 1 0 7.2H7v-7.2ZM7 4v14"/>',
  italic: '<path d="M10 4h8M6 20h8M14 4 10 20"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6h.01M4 12h.01M4 18h.01"/>',
  'list-ordered': '<path d="M10 6h10M10 12h10M10 18h10"/><path d="M4 5h1v3M3.5 8h2.5M3.5 11.5c0-1 2.5-1 2.5.2 0 .9-2.5 1.3-2.5 2.8h2.7M3.5 17.5c0-1 2.5-1 2.5.2 0 .9-2.5 1.3-2.5 2.8h2.7"/>',
  align: '<path d="M4 6h16M4 10h12M4 14h16M4 18h10"/>',
  link: '<path d="M10 13.8 8.6 15.2a3.4 3.4 0 0 1-4.8-4.8l2.1-2.1A3.4 3.4 0 0 1 10.7 8"/><path d="m14 10.2 1.4-1.4a3.4 3.4 0 0 1 4.8 4.8l-2.1 2.1a3.4 3.4 0 0 1-4.8 0"/><path d="m8.5 12 7-0.1"/>',
  eye: '<path d="M2.5 12s3.2-5 9.5-5 9.5 5 9.5 5-3.2 5-9.5 5-9.5-5-9.5-5Z"/><circle cx="12" cy="12" r="2.2"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5M4 20h16"/>',
  x: '<path d="m6 6 12 12M18 6 6 18"/>',
  save: '<path d="M5 3h12l2 2v16H5V3Z"/><path d="M8 3v6h8V3M8 21v-7h8v7"/>',
  'clipboard-check': '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4.5V3h6v1.5M8.5 12l2.2 2.2 4.8-4.8"/>',
  calendar: '<rect x="3" y="4.5" width="18" height="16" rx="2"/><path d="M16 2.5v4M8 2.5v4M3 9h18"/>',
  target: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/>',
  search: '<circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 4.5 4.5"/>',
  upload: '<path d="M12 15V3M7 8l5-5 5 5M4 14v5h16v-5"/>',
  'book-marked': '<path d="M6 3.5h12a1 1 0 0 1 1 1v16l-7-3.8-7 3.8v-16a1 1 0 0 1 1-1Z"/><path d="M8.5 8.5h7M8.5 12h5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  'alert-circle': '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/>',
  user: '<circle cx="12" cy="8" r="3.5"/><path d="M4.5 20c.7-3.4 3.2-5 7.5-5s6.8 1.6 7.5 5"/>',
  archive: '<path d="M4 7h16v13H4V7ZM3 3h18v4H3V3Z"/><path d="M9 12h6"/>',
  'external-link': '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5"/>',
  'file-plus': '<path d="M14 2.8H6.8A1.8 1.8 0 0 0 5 4.6v14.8a1.8 1.8 0 0 0 1.8 1.8h10.4a1.8 1.8 0 0 0 1.8-1.8V7.4L14 2.8Z"/><path d="M14 3v4.5h5.2M12 11v6M9 14h6"/>',
  'panel-left': '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  type: '<path d="M4 5V3h16v2M12 3v18M8 21h8"/>',
  'list-checks': '<path d="m3 6 1.5 1.5L7 5M10 6h11M3 12h2M9 12h12M3 18h2M9 18h12M3 6h.01M3 12h.01M3 18h.01"/>',
  rotate: '<path d="M4 10a8 8 0 0 1 14-3l2 2"/><path d="M20 4v5h-5M20 14a8 8 0 0 1-14 3l-2-2"/><path d="M4 20v-5h5"/>',
  'circle-check': '<circle cx="12" cy="12" r="9"/><path d="m8 12 2.6 2.6 5.4-5.4"/>',
  circle: '<circle cx="12" cy="12" r="8.5"/>',
};

let state;
let saveTimer = null;

function icon(name, className = '') {
  return `<svg class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_PATHS[name] || ICON_PATHS.circle}</svg>`;
}

function hydrateIcons(root = document) {
  root.querySelectorAll('[data-icon]').forEach((element) => {
    const name = element.getAttribute('data-icon');
    element.innerHTML = icon(name);
  });
}

function createId(prefix = 'id') {
  if (window.crypto && typeof window.crypto.randomUUID === 'function') {
    return `${prefix}-${window.crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function getDefaultTasks(type) {
  const labels = {
    introduction: ['Formuler la problématique', 'Présenter les objectifs', 'Annoncer le plan'],
    problematique: ['Délimiter le sujet', 'Définir les questions de recherche', 'Écrire les hypothèses'],
    'cadre-theorique': ['Définir les concepts clés', 'Sélectionner les auteurs', 'Synthétiser les approches'],
    methodologie: ['Présenter l’échantillon', 'Décrire les outils', 'Anticiper les limites'],
    resultats: ['Organiser les résultats', 'Ajouter les figures', 'Commenter les tendances'],
    discussion: ['Interpréter les résultats', 'Comparer avec la littérature', 'Formuler les perspectives'],
    conclusion: ['Répondre à la problématique', 'Synthétiser les apports', 'Terminer par les perspectives'],
    annexes: ['Numéroter les annexes', 'Ajouter les documents', 'Vérifier la lisibilité'],
    autre: ['Définir l’objectif', 'Organiser les sous-sections', 'Ajouter une transition'],
  };
  return (labels[type] || labels.autre).map((label, index) => ({
    id: createId(`task-${index}`),
    label,
    done: false,
  }));
}

function createSection(title, type = 'autre', content = '', completed = false) {
  return {
    id: createId('section'),
    title,
    type,
    content,
    completed,
    updatedAt: Date.now(),
    tasks: getDefaultTasks(type),
  };
}

function createDefaultSections() {
  return DEFAULT_SECTION_BLUEPRINTS.map((blueprint) => createSection(blueprint.title, blueprint.type));
}

function createDefaultChecklist() {
  return [
    { id: createId('check'), label: 'Choisir et délimiter son sujet', done: false },
    { id: createId('check'), label: 'Formuler sa problématique', done: false },
    { id: createId('check'), label: 'Établir son plan détaillé', done: false },
    { id: createId('check'), label: 'Constituer sa bibliographie', done: false },
    { id: createId('check'), label: 'Planifier les rel lectures', done: false },
  ];
}

function createStarterProject() {
  const topic = 'Les réseaux sociaux et la santé mentale des adolescents';
  return {
    id: createId('project'),
    title: topic,
    field: 'Sciences sociales et psychologie',
    level: 'Master 1',
    targetWords: 10000,
    deadline: addDaysToIso(45),
    createdAt: Date.now(),
    updatedAt: Date.now(),
    isDemo: true,
    sections: [
      createSection(
        'Introduction générale',
        'introduction',
        `Dans un contexte marqué par l’usage croissant des plateformes numériques, la question de la santé mentale des adolescents occupe une place importante dans les débats actuels. Le sujet invite à examiner les liens entre l’exposition aux réseaux sociaux et le bien-être psychique des jeunes.\n\nProblématique : dans quelle mesure l’usage des réseaux sociaux peut-il être associé à l’évolution de la santé mentale des adolescents, et selon quelles conditions ?\n\nCette étude cherche à mieux comprendre les mécanismes perceptibles derrière cette relation afin de formuler des recommandations utiles aux adultes et aux institutions.`,
        true
      ),
      createSection(
        'Revue de la littérature',
        'cadre-theorique',
        `La revue de la littérature doit mobiliser les notions d’usage intensif, de comparaison sociale et de validation. Elle pourra comparer plusieurs approches : les travaux portant sur les effets des écrans, ceux qui expliquent le rôle des interactions en ligne et les études consacrées aux facteurs de protection.\n\nÀ personnaliser : présenter les auteurs retenus, leur période et leurs principaux résultats avant de construire une synthèse critique.`,
        true
      ),
      createSection(
        'Méthodologie',
        'methodologie',
        `La méthodologie devra préciser la population ciblée, la période d’enquête, les outils de collecte et la méthode d’analyse. Il est important de distinguer les données recueillies des interprétations et d’expliquer les limites de l’étude.\n\nÀ compléter selon votre choix méthodologique : entretien qualitatif, questionnaire, analyse thématique ou approche mixte.`,
      ),
      createSection(
        'Résultats',
        'resultats',
        `Cette partie servira à présenter les informations recueillies de façon organisée. Les résultats pourront être regroupés par thème, avec des tableaux ou des figures pour faciliter la lecture. Chaque tendance observée devra être reliée à une question de la problématique.\n\nÀ compléter après la collecte et l’analyse des données.`,
      ),
      createSection(
        'Discussion',
        'discussion',
        `La discussion interprète les résultats à la lumière du cadre théorique et des travaux consultés. Elle pourra discuter les accords et les écarts observés, les limites méthodologiques et les implications pratiques.\n\nÀ compléter avec vos propres résultats et références.`,
      ),
      createSection(
        'Conclusion générale',
        'conclusion',
        `La conclusion répondra à la problématique posée en introduction. Elle synthétisera les principaux éléments mis en évidence, précisera les contributions du travail et ouvrira sur des perspectives de recherche ou d’action.\n\nÀ finaliser après la rédaction de l’ensemble du mémoire.`,
      ),
    ],
    citations: [
      {
        id: createId('citation'),
        author: 'Auteur, A.',
        year: '2024',
        title: 'Une référence à vérifier avant l’insertion finale',
        source: 'Article scientifique',
        url: '',
        createdAt: Date.now(),
      },
    ],
    checklist: [
      { id: createId('check'), label: 'Définir le sujet et son périmètre', done: true },
      { id: createId('check'), label: 'Formuler une problématique précise', done: true },
      { id: createId('check'), label: 'Construire le plan du mémoire', done: true },
      { id: createId('check'), label: 'Réunir et vérifier les sources', done: false },
      { id: createId('check'), label: 'Organiser les prochaines rel lectures', done: false },
    ],
  };
}

function addDaysToIso(days) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

function getInitialState() {
  const project = createStarterProject();
  return {
    version: 1,
    user: { name: 'Camille Martin' },
    projects: [project],
    activeProjectId: project.id,
    currentSectionId: project.sections[0].id,
    view: 'dashboard',
    preferences: {
      dailyGoal: 500,
      showAssistant: true,
    },
  };
}

function normalizeState(raw) {
  const fallback = getInitialState();
  const normalized = raw && typeof raw === 'object' ? raw : fallback;
  normalized.version = 1;
  normalized.user = normalized.user && typeof normalized.user === 'object'
    ? normalized.user
    : fallback.user;
  normalized.user.name = String(normalized.user.name || 'Camille Martin');
  normalized.preferences = {
    ...fallback.preferences,
    ...(normalized.preferences || {}),
  };
  normalized.projects = Array.isArray(normalized.projects) ? normalized.projects : [];
  normalized.projects = normalized.projects.map(normalizeProject).filter(Boolean);
  if (normalized.projects.length === 0) {
    normalized.projects = [createStarterProject()];
  }
  if (!normalized.projects.some((project) => project.id === normalized.activeProjectId)) {
    normalized.activeProjectId = normalized.projects[0].id;
  }
  const activeProject = getProjectFrom(normalized, normalized.activeProjectId);
  if (!activeProject.sections.some((section) => section.id === normalized.currentSectionId)) {
    normalized.currentSectionId = activeProject.sections[0]?.id || null;
  }
  if (!['dashboard', 'editor', 'bibliography', 'settings'].includes(normalized.view)) {
    normalized.view = 'dashboard';
  }
  if (normalized.view === 'editor' && !activeProject.sections.length) {
    normalized.view = 'dashboard';
  }
  return normalized;
}

function normalizeProject(project) {
  if (!project || typeof project !== 'object') return null;
  project.id = project.id || createId('project');
  project.title = String(project.title || 'Mémoire sans titre');
  project.field = String(project.field || '');
  project.level = String(project.level || '');
  project.targetWords = Number(project.targetWords) || 10000;
  project.deadline = project.deadline || '';
  project.createdAt = project.createdAt || Date.now();
  project.updatedAt = project.updatedAt || project.createdAt;
  project.sections = Array.isArray(project.sections) ? project.sections : [];
  project.sections = project.sections.map((section) => {
    section.id = section.id || createId('section');
    section.title = String(section.title || 'Nouvelle partie');
    section.type = SECTION_TYPES[section.type] ? section.type : 'autre';
    section.content = typeof section.content === 'string' ? section.content : '';
    section.completed = Boolean(section.completed);
    section.updatedAt = section.updatedAt || Date.now();
    section.tasks = Array.isArray(section.tasks) ? section.tasks : getDefaultTasks(section.type);
    section.tasks = section.tasks.map((task) => ({
      id: task.id || createId('task'),
      label: String(task.label || 'Nouvelle étape'),
      done: Boolean(task.done),
    }));
    return section;
  });
  project.citations = Array.isArray(project.citations) ? project.citations : [];
  project.citations = project.citations.map((citation) => ({
    id: citation.id || createId('citation'),
    author: String(citation.author || 'Auteur inconnu'),
    year: String(citation.year || 'n.d.'),
    title: String(citation.title || 'Référence sans titre'),
    source: String(citation.source || 'Source non précisée'),
    url: String(citation.url || ''),
    createdAt: citation.createdAt || Date.now(),
  }));
  project.checklist = Array.isArray(project.checklist) && project.checklist.length
    ? project.checklist
    : createDefaultChecklist();
  project.checklist = project.checklist.map((item) => ({
    id: item.id || createId('check'),
    label: String(item.label || 'Nouvelle étape'),
    done: Boolean(item.done),
  }));
  return project;
}

function loadState() {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored) return normalizeState(JSON.parse(stored));
  } catch (error) {
    console.warn('Impossible de charger les données locales.', error);
  }
  return getInitialState();
}

function persist() {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch (error) {
    console.warn('Impossible d’enregistrer les données locales.', error);
  }
}

function getProjectFrom(source, projectId) {
  return source.projects.find((project) => project.id === projectId) || source.projects[0];
}

function getProject(projectId = state.activeProjectId) {
  return state.projects.find((project) => project.id === projectId) || state.projects[0];
}

function getSection(project = getProject(), sectionId = state.currentSectionId) {
  return project?.sections.find((section) => section.id === sectionId) || project?.sections[0];
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;',
  }[character]));
}

function wordCount(text = '') {
  const trimmed = String(text).trim();
  if (!trimmed) return 0;
  return trimmed.split(/\s+/).filter(Boolean).length;
}

function formatNumber(value) {
  return new Intl.NumberFormat('fr-FR').format(Number(value) || 0);
}

function formatDate(value, options = {}) {
  if (!value) return 'Non définie';
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('fr-FR', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    ...options,
  }).format(date);
}

function formatDateTime(value) {
  if (!value) return 'à l’instant';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'à l’instant';
  return new Intl.DateTimeFormat('fr-FR', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function getInitials(name = '') {
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return 'CM';
  return parts.slice(0, 2).map((part) => part[0].toUpperCase()).join('');
}

function daysUntil(value) {
  if (!value) return null;
  const target = new Date(`${value}T23:59:59`);
  const now = new Date();
  if (Number.isNaN(target.getTime())) return null;
  return Math.ceil((target.getTime() - now.getTime()) / 86400000);
}

function getSectionStatus(section) {
  if (section.completed) return { label: 'Terminé', className: 'done', iconName: 'check' };
  if (section.content.trim()) return { label: 'En cours', className: 'draft', iconName: 'pen-line' };
  return { label: 'À rédiger', className: 'empty', iconName: 'circle' };
}

function getProjectProgress(project) {
  if (!project || !project.sections.length) return 0;
  const completed = project.sections.filter((section) => section.completed).length;
  return Math.round((completed / project.sections.length) * 100);
}

function getProjectWords(project) {
  return (project?.sections || []).reduce((total, section) => total + wordCount(section.content), 0);
}

function getProjectCompletedSections(project) {
  return (project?.sections || []).filter((section) => section.completed).length;
}

function getInitialsLabel() {
  return getInitials(state.user.name);
}

function render() {
  const main = document.getElementById('main-content');
  if (!main) return;
  if (state.view === 'editor' && (!getProject() || !getProject().sections.length)) {
    state.view = 'dashboard';
  }
  const templates = {
    dashboard: renderDashboard,
    editor: renderEditor,
    bibliography: renderBibliography,
    settings: renderSettings,
  };
  main.innerHTML = (templates[state.view] || renderDashboard)();
  hydrateIcons(main);
  updateNavigation();
  updateProfile();
}

function updateNavigation() {
  document.querySelectorAll('#primary-nav [data-view]').forEach((button) => {
    const targetView = button.dataset.view;
    const isActive = targetView === state.view || (targetView === 'editor' && state.view === 'editor');
    button.classList.toggle('active', isActive);
  });
}

function updateProfile() {
  const nameElement = document.getElementById('sidebar-user-name');
  if (nameElement) nameElement.textContent = state.user.name;
  const avatar = document.querySelector('.avatar');
  if (avatar) avatar.textContent = getInitialsLabel();
}

function renderDashboard() {
  const activeProject = getProject();
  const totalWords = state.projects.reduce((total, project) => total + getProjectWords(project), 0);
  const totalSections = state.projects.reduce((total, project) => total + project.sections.length, 0);
  const completedSections = state.projects.reduce((total, project) => total + getProjectCompletedSections(project), 0);
  const totalCitations = state.projects.reduce((total, project) => total + project.citations.length, 0);
  const projects = [...state.projects].sort((a, b) => b.updatedAt - a.updatedAt);
  const progress = getProjectProgress(activeProject);
  const remainingDays = daysUntil(activeProject?.deadline);
  const checklist = activeProject?.checklist || [];
  const doneChecklist = checklist.filter((item) => item.done).length;

  return `
    <div class="page-container">
      <header class="page-header">
        <div>
          <p class="eyebrow">Vue d’ensemble</p>
          <h1 class="page-title">Bonjour, ${escapeHtml(firstName(state.user.name))} <span class="wave">👋</span></h1>
          <p class="page-subtitle">Votre espace de rédaction pour avancer avec méthode, une idée à la fois.</p>
        </div>
        <button class="button button--primary" type="button" data-action="new-project">
          ${icon('plus')} Nouveau mémoire
        </button>
      </header>

      <section class="stat-grid" aria-label="Statistiques de votre espace">
        <article class="stat-card">
          <div class="stat-top"><span class="stat-label">Projets actifs</span><span class="stat-icon">${icon('book-open')}</span></div>
          <strong class="stat-value">${formatNumber(state.projects.length)}</strong>
          <span class="stat-detail">${projects.length > 1 ? 'dans votre espace' : 'dans votre espace'}</span>
        </article>
        <article class="stat-card stat-card--mint">
          <div class="stat-top"><span class="stat-label">Mots rédigés</span><span class="stat-icon">${icon('pen-line')}</span></div>
          <strong class="stat-value">${formatNumber(totalWords)}</strong>
          <span class="stat-detail">tous projets confondus</span>
        </article>
        <article class="stat-card stat-card--amber">
          <div class="stat-top"><span class="stat-label">Parties terminées</span><span class="stat-icon">${icon('check-circle')}</span></div>
          <strong class="stat-value">${formatNumber(completedSections)}<span style="font-size: 15px; color: var(--muted-light); font-weight: 500;">/${formatNumber(totalSections)}</span></strong>
          <span class="stat-detail">dans votre plan actuel</span>
        </article>
        <article class="stat-card stat-card--rose">
          <div class="stat-top"><span class="stat-label">Références</span><span class="stat-icon">${icon('quote')}</span></div>
          <strong class="stat-value">${formatNumber(totalCitations)}</strong>
          <span class="stat-detail">dans votre bibliographie</span>
        </article>
      </section>

      <div class="dashboard-grid">
        <section class="panel">
          <div class="panel-header">
            <div><h2 class="panel-title">Mes mémoires</h2><p class="panel-description">Reprenez votre travail là où vous l’avez laissé.</p></div>
            <button class="text-link" type="button" data-action="new-project">${icon('plus')} Ajouter</button>
          </div>
          <div class="project-list">
            ${projects.length ? projects.map(renderProjectRow).join('') : renderEmptyProjects()}
          </div>
        </section>

        <section class="panel">
          <div class="panel-header">
            <div><h2 class="panel-title">Progression actuelle</h2><p class="panel-description">${escapeHtml(activeProject?.title || 'Aucun projet sélectionné')}</p></div>
            <button class="text-link" type="button" data-view="editor">Ouvrir ${icon('arrow-right')}</button>
          </div>
          <div class="progress-panel-body">
            <div class="progress-ring" style="--progress: ${progress}%;"><div class="progress-ring-content"><strong class="progress-ring-value">${progress}%</strong><span class="progress-ring-label">accompli</span></div></div>
            <div class="progress-copy">
              <h3>${progress === 100 ? 'Bravo, vous avez terminé !' : 'Vous êtes sur la bonne voie'}</h3>
              <p>${remainingDays === null ? 'Ajoutez une date cible pour suivre votre rythme.' : remainingDays >= 0 ? `Il reste ${remainingDays} jour${remainingDays > 1 ? 's' : ''} avant votre échéance.` : 'Votre échéance est passée : actualisez-la dans les réglages.'}</p>
              <div class="progress-track"><div class="progress-fill" style="width: ${progress}%;"></div></div>
            </div>
          </div>
        </section>
      </div>

      <div class="lower-grid">
        <section class="panel checklist-panel">
          <div class="panel-header">
            <div><h2 class="panel-title">Étapes essentielles</h2><p class="panel-description">${doneChecklist} sur ${checklist.length} étapes terminées</p></div>
            <span class="badge ${doneChecklist === checklist.length && checklist.length ? 'badge--mint' : 'badge--gray'}">${checklist.length ? Math.round((doneChecklist / checklist.length) * 100) : 0}%</span>
          </div>
          <div class="checklist-list">
            ${checklist.length ? checklist.map(renderChecklistItem).join('') : '<div class="empty-state"><p>Créez un projet pour afficher votre checklist.</p></div>'}
          </div>
        </section>
        <aside class="tip-card">
          <div class="stat-icon">${icon('sparkles')}</div>
          <h3>La première étape n’a pas à être parfaite.</h3>
          <p>Créez une première version de votre plan, puis affinez-la à mesure que votre lecture vous éclaire. Une mémoire se construit par itérations.</p>
          <button class="button button--soft button--small" type="button" data-action="show-help">Voir le guide ${icon('arrow-right')}</button>
        </aside>
      </div>
    </div>
  `;
}

function renderProjectRow(project) {
  const progress = getProjectProgress(project);
  const words = getProjectWords(project);
  const isActive = project.id === state.activeProjectId;
  return `
    <div class="project-row">
      <div class="project-cover">${icon('file-text')}</div>
      <div class="project-row-main">
        <span class="project-row-title" title="${escapeHtml(project.title)}">${escapeHtml(project.title)}</span>
        <div class="project-row-meta"><span>${escapeHtml(project.field || 'Discipline non renseignée')}</span><i class="separator"></i><span>${formatNumber(words)} mots</span>${project.isDemo ? '<span class="badge badge--gray" style="margin-left: 4px;">exemple</span>' : ''}</div>
      </div>
      <div class="project-row-progress">
        <div class="progress-label"><span>Progression</span><strong>${progress}%</strong></div>
        <div class="progress-track"><div class="progress-fill ${progress === 100 ? 'progress-fill--mint' : ''}" style="width: ${progress}%;"></div></div>
      </div>
      <button class="project-row-action" type="button" data-action="open-project" data-project-id="${project.id}" aria-label="Ouvrir ${escapeHtml(project.title)}">${icon('arrow-right')}</button>
    </div>
  `;
}

function renderEmptyProjects() {
  return `
    <div class="empty-state">
      <div class="empty-state-icon">${icon('book-open')}</div>
      <h3>Aucun projet pour le moment</h3>
      <p>Créez votre premier espace de mémoire pour organiser vos idées et vos parties.</p>
      <button class="button button--soft button--small" type="button" data-action="new-project">${icon('plus')} Créer un mémoire</button>
    </div>
  `;
}

function renderChecklistItem(item) {
  return `
    <div class="checklist-item ${item.done ? 'is-done' : ''}">
      <button class="check-box ${item.done ? 'checked' : ''}" type="button" data-action="toggle-check" data-check-id="${item.id}" aria-label="${item.done ? 'Décocher' : 'Cocher'} : ${escapeHtml(item.label)}">${item.done ? icon('check') : ''}</button>
      <span class="checklist-copy">${escapeHtml(item.label)}</span>
      ${item.done ? '<span class="checklist-badge">fait</span>' : ''}
    </div>
  `;
}

function renderEditor() {
  const project = getProject();
  if (!project) return renderDashboard();
  let section = getSection(project);
  if (!section && project.sections.length) {
    section = project.sections[0];
    state.currentSectionId = section.id;
  }
  if (!section) {
    return `<div class="page-container"><div class="panel empty-state"><div class="empty-state-icon">${icon('file-text')}</div><h3>Votre mémoire est vide</h3><p>Ajoutez une première partie pour commencer à rédiger.</p><button class="button button--primary" data-action="add-section">${icon('plus')} Ajouter une partie</button></div></div>`;
  }
  const status = getSectionStatus(section);
  const guidance = SECTION_TYPES[section.type] || SECTION_TYPES.autre;
  const words = wordCount(section.content);
  const projectProgress = getProjectProgress(project);
  const remainingDays = daysUntil(project.deadline);
  const completedTasks = section.tasks.filter((task) => task.done).length;

  return `
    <div class="editor-page page-container">
      <div class="editor-breadcrumb">
        <button type="button" data-view="dashboard">Mes mémoires</button>
        <span>${icon('chevron-right')}</span>
        <span class="current">${escapeHtml(project.title)}</span>
      </div>
      <header class="editor-project-header">
        <div class="project-heading">
          <p class="eyebrow">${escapeHtml(project.field || 'Projet académique')}</p>
          <input id="project-title-input" class="project-title-input" type="text" value="${escapeHtml(project.title)}" aria-label="Titre du mémoire" />
          <div class="project-meta-line">
            <span>${escapeHtml(project.level || 'Niveau non renseigné')}</span><i class="separator"></i>
            <span>${formatNumber(project.targetWords)} mots visés</span><i class="separator"></i>
            <span>Échéance : ${escapeHtml(formatDate(project.deadline))}</span>
            ${remainingDays !== null && remainingDays >= 0 ? `<i class="separator"></i><span>${remainingDays} j restants</span>` : ''}
          </div>
        </div>
        <div class="editor-actions">
          <button class="button button--secondary" type="button" data-action="preview-project">${icon('eye')} Aperçu</button>
          <button class="button button--primary" type="button" data-action="export-word">${icon('download')} Exporter</button>
        </div>
      </header>

      <div class="editor-layout ${state.preferences.showAssistant ? '' : 'editor-layout--solo'}">
        <aside class="outline-panel">
          <div class="outline-header"><h2>Plan du mémoire</h2><span class="outline-count">${project.sections.length}</span></div>
          <div class="outline-progress" id="outline-progress">
            <div class="progress-label"><span>Progression globale</span><strong id="outline-progress-value">${projectProgress}%</strong></div>
            <div class="progress-track"><div class="progress-fill" id="outline-progress-bar" style="width: ${projectProgress}%;"></div></div>
          </div>
          <div class="outline-list">
            ${project.sections.map((item) => renderOutlineItem(item, section.id)).join('')}
          </div>
          <button class="outline-add" type="button" data-action="add-section">${icon('plus')} Ajouter une partie</button>
        </aside>

        <section class="editor-column" aria-label="Éditeur de la partie">
          <div class="editor-column-header">
            <div class="section-heading">
              <span class="section-type-label">${escapeHtml(guidance.label)}</span>
              <input id="section-title-input" class="section-title-input" type="text" value="${escapeHtml(section.title)}" aria-label="Titre de la partie" />
            </div>
            <div class="editor-header-actions">
              <select id="section-type-select" class="section-select" aria-label="Type de partie">
                ${Object.entries(SECTION_TYPES).map(([key, value]) => `<option value="${key}" ${key === section.type ? 'selected' : ''}>${escapeHtml(value.shortLabel)}</option>`).join('')}
              </select>
              <button class="icon-button" type="button" data-action="duplicate-section" aria-label="Dupliquer la partie">${icon('copy')}</button>
              <button class="icon-button" type="button" data-action="delete-section" aria-label="Supprimer la partie">${icon('trash')}</button>
              <button class="button button--small ${section.completed ? 'button--soft' : 'button--secondary'}" type="button" data-action="toggle-section-done">${icon(section.completed ? 'check-circle' : 'circle-check')} ${section.completed ? 'Terminée' : 'Terminer'}</button>
            </div>
          </div>
          <div class="editor-toolbar" aria-label="Mise en forme">
            <button class="toolbar-icon" type="button" data-action="format-text" data-format="bold" aria-label="Gras">${icon('bold')}</button>
            <button class="toolbar-icon" type="button" data-action="format-text" data-format="italic" aria-label="Italique">${icon('italic')}</button>
            <span class="toolbar-divider"></span>
            <button class="toolbar-icon" type="button" data-action="format-text" data-format="heading" aria-label="Titre">${icon('type')}</button>
            <button class="toolbar-icon" type="button" data-action="format-text" data-format="list" aria-label="Liste à puces">${icon('list')}</button>
            <button class="toolbar-icon" type="button" data-action="format-text" data-format="ordered-list" aria-label="Liste numérotée">${icon('list-ordered')}</button>
            <button class="toolbar-icon" type="button" data-action="format-text" data-format="quote" aria-label="Citation">${icon('quote')}</button>
            <span class="toolbar-divider"></span>
            <button class="toolbar-icon" type="button" data-action="insert-citation" aria-label="Insérer une référence">${icon('link')}</button>
            <span class="toolbar-spacer"></span>
            <span class="editor-status"><i class="status-dot"></i><span id="save-status">Enregistré automatiquement</span></span>
          </div>
          <textarea id="section-editor" class="editor-textarea" spellcheck="true" placeholder="Commencez à écrire votre partie ici…">${escapeHtml(section.content)}</textarea>
          <div class="editor-footer">
            <div class="editor-footer-stats"><span><strong id="editor-word-count">${formatNumber(words)}</strong> mots</span><span><strong id="editor-character-count">${formatNumber(section.content.length)}</strong> caractères</span></div>
            <span>${status.label} · sauvegardé ${escapeHtml(formatDateTime(section.updatedAt))}</span>
          </div>
        </section>

        ${state.preferences.showAssistant ? `<aside class="assistant-panel">` : ''}
          <div class="assistant-header">
            <div class="assistant-avatar">${icon('sparkles')}</div>
            <div><strong>Assistant de rédaction</strong><span>Un coup de pouce local</span></div>
          </div>
          <div class="assistant-block">
            <div class="assistant-label">Objectif de la partie <small>${completedTasks}/${section.tasks.length}</small></div>
            <p class="assistant-text">${escapeHtml(guidance.guidance)}</p>
          </div>
          <div class="assistant-block">
            <div class="assistant-label">À vérifier <small>liste</small></div>
            <ul class="assistant-list">${guidance.bullets.map((bullet) => `<li>${escapeHtml(bullet)}</li>`).join('')}</ul>
          </div>
          <div class="assistant-block">
            <div class="assistant-label">Petites actions</div>
            <div class="assistant-tasks">${section.tasks.map(renderAssistantTask).join('')}</div>
          </div>
          <div class="assistant-block">
            <div class="assistant-callout"><p><strong>Conseil :</strong> ${escapeHtml(guidance.tip)}</p></div>
          </div>
          <div class="assistant-actions">
            <button class="button button--soft button--small button--wide" type="button" data-action="generate-draft">${icon('wand-sparkles')} Générer un brouillon</button>
            <button class="button button--secondary button--small button--wide" type="button" data-action="insert-citation">${icon('quote')} Ajouter une référence</button>
          </div>
        ${state.preferences.showAssistant ? '</aside>' : ''}
      </div>
    </div>
  `;
}

function renderOutlineItem(section, activeSectionId) {
  const status = getSectionStatus(section);
  return `
    <button class="outline-item ${section.id === activeSectionId ? 'active' : ''}" type="button" data-action="select-section" data-section-id="${section.id}">
      <span class="outline-item-status ${status.className}">${status.iconName === 'circle' ? '' : icon(status.iconName)}</span>
      <span class="outline-item-copy"><span class="outline-item-title" data-outline-title="${section.id}">${escapeHtml(section.title)}</span><span class="outline-item-type">${escapeHtml(SECTION_TYPES[section.type]?.shortLabel || 'Partie')}</span></span>
    </button>
  `;
}

function renderAssistantTask(task) {
  return `
    <button class="assistant-task" type="button" data-action="toggle-task" data-task-id="${task.id}">
      <span class="check-box ${task.done ? 'checked' : ''}" aria-hidden="true">${task.done ? icon('check') : ''}</span>
      <span>${escapeHtml(task.label)}</span>
    </button>
  `;
}

function renderBibliography() {
  const project = getProject();
  if (!project) return renderDashboard();
  const citations = [...project.citations].sort((a, b) => b.createdAt - a.createdAt);
  return `
    <div class="page-container">
      <header class="page-header">
        <div>
          <p class="eyebrow">Sources & références</p>
          <h1 class="page-title">Bibliographie</h1>
          <p class="page-subtitle">Centralisez vos sources et insérez-les facilement dans la rédaction.</p>
        </div>
        <button class="button button--primary" type="button" data-action="add-citation">${icon('plus')} Ajouter une référence</button>
      </header>
      <div class="bibliography-layout">
        <section class="panel">
          <div class="panel-header"><div><h2 class="panel-title">Références du projet</h2><p class="panel-description">${citations.length} source${citations.length > 1 ? 's' : ''} · ${escapeHtml(project.title)}</p></div><span class="badge">${formatNumber(citations.length)}</span></div>
          <div class="citation-list">
            ${citations.length ? citations.map((citation, index) => renderCitationRow(citation, index)).join('') : `<div class="empty-state"><div class="empty-state-icon">${icon('library')}</div><h3>Votre bibliographie est vide</h3><p>Ajoutez vos articles, livres, rapports et ressources pour les retrouver au moment opportun.</p><button class="button button--soft button--small" type="button" data-action="add-citation">${icon('plus')} Ajouter ma première source</button></div>`}
          </div>
        </section>
        <aside class="bibliography-side">
          <div class="format-card">
            <div class="stat-icon">${icon('book-marked')}</div>
            <h3>Des sources mieux utilisées</h3>
            <p>Une référence n’est utile que lorsqu’elle est reliée à une idée. Prenez des notes dès votre lecture.</p>
            <button class="button button--soft button--small" type="button" data-action="show-help">${icon('info')} Voir les conseils</button>
          </div>
          <section class="panel bibliography-rules">
            <h3>Bonnes pratiques</h3>
            <div class="rule-row"><span class="rule-number">1</span><p>Notez l’auteur, l’année et la page dès que vous lisez.</p></div>
            <div class="rule-row"><span class="rule-number">2</span><p>Reliez chaque source à une citation ou une idée précise.</p></div>
            <div class="rule-row"><span class="rule-number">3</span><p>Vérifiez les informations avant la version finale.</p></div>
            <div class="rule-row"><span class="rule-number">4</span><p>Adaptez la norme de citation à votre établissement.</p></div>
          </section>
        </aside>
      </div>
    </div>
  `;
}

function renderCitationRow(citation, index) {
  return `
    <div class="citation-row">
      <div class="citation-index">${index + 1}</div>
      <div class="citation-main">
        <span class="citation-title" title="${escapeHtml(citation.title)}">${escapeHtml(citation.title)}</span>
        <div class="citation-meta"><span>${escapeHtml(citation.author)} (${escapeHtml(citation.year)})</span><span class="citation-source">${escapeHtml(citation.source)}</span>${citation.url ? '<span class="citation-source">lien disponible</span>' : ''}</div>
      </div>
      <div class="citation-actions">
        <button class="icon-button" type="button" data-action="insert-citation-from-list" data-citation-id="${citation.id}" aria-label="Insérer dans le texte">${icon('quote')}</button>
        <button class="icon-button" type="button" data-action="edit-citation" data-citation-id="${citation.id}" aria-label="Modifier">${icon('edit')}</button>
        <button class="icon-button" type="button" data-action="delete-citation" data-citation-id="${citation.id}" aria-label="Supprimer">${icon('trash')}</button>
      </div>
    </div>
  `;
}

function renderSettings() {
  const activeProject = getProject();
  return `
    <div class="page-container">
      <header class="page-header">
        <div>
          <p class="eyebrow">Préférences</p>
          <h1 class="page-title">Réglages</h1>
          <p class="page-subtitle">Personnalisez votre espace de travail et gérez vos données locales.</p>
        </div>
      </header>
      <div class="settings-layout">
        <section class="panel settings-card">
          <h2>Profil de rédaction</h2>
          <p>Ces informations sont utilisées uniquement dans cet espace.</p>
          <form id="settings-form">
            <div class="form-grid">
              <label class="form-field form-field--full"><span class="form-label">Votre nom</span><input class="input" type="text" name="name" value="${escapeHtml(state.user.name)}" placeholder="Votre nom" required /></label>
              <label class="form-field"><span class="form-label">Objectif quotidien</span><select class="select" name="dailyGoal"><option value="250" ${Number(state.preferences.dailyGoal) === 250 ? 'selected' : ''}>250 mots / jour</option><option value="500" ${Number(state.preferences.dailyGoal) === 500 ? 'selected' : ''}>500 mots / jour</option><option value="1000" ${Number(state.preferences.dailyGoal) === 1000 ? 'selected' : ''}>1 000 mots / jour</option><option value="0" ${Number(state.preferences.dailyGoal) === 0 ? 'selected' : ''}>Sans objectif</option></select></label>
              <label class="form-field"><span class="form-label">Projet actuel</span><select class="select" name="activeProjectId">${state.projects.map((project) => `<option value="${project.id}" ${project.id === state.activeProjectId ? 'selected' : ''}>${escapeHtml(project.title)}</option>`).join('')}</select></label>
            </div>
            <div class="form-actions" style="margin-top: 22px;"><button class="button button--primary" type="submit">${icon('save')} Enregistrer les préférences</button></div>
          </form>
        </section>
        <div class="settings-layout-side" style="display: grid; gap: 18px;">
          <section class="panel settings-card">
            <h2>Préférences d’affichage</h2>
            <p>Choisissez les repères qui vous aident à rester concentré·e.</p>
            <div class="preferences-list">
              <div class="preference-row"><div><strong>Assistant de rédaction</strong><span>Afficher les conseils de la partie active</span></div><button class="toggle ${state.preferences.showAssistant ? 'on' : ''}" type="button" data-action="toggle-preference" data-preference="showAssistant" aria-label="Afficher l’assistant"></button></div>
              <div class="preference-row"><div><strong>Suivi de l’objectif</strong><span>Afficher les mots et l’échéance dans l’éditeur</span></div><button class="toggle on" type="button" data-action="show-info">${icon('info')}</button></div>
            </div>
          </section>
          <section class="panel danger-zone">
            <h2>Vos données</h2>
            <p>Vos mémoires sont stockées dans ce navigateur. Pensez à exporter une sauvegarde avant de changer d’appareil.</p>
            <div class="form-actions" style="justify-content: flex-start; margin-top: 17px;">
              <button class="button button--secondary button--small" type="button" data-action="export-backup">${icon('download')} Exporter une sauvegarde</button>
              <button class="button button--danger button--small" type="button" data-action="reset-data">${icon('rotate')} Réinitialiser</button>
            </div>
          </section>
        </div>
      </div>
    </div>
  `;
}

function firstName(name) {
  return String(name || 'Camille').trim().split(/\s+/)[0] || 'Camille';
}

function openModal(content, className = '') {
  const root = document.getElementById('modal-root');
  if (!root) return;
  root.innerHTML = `<div class="modal-backdrop" data-modal-backdrop="true">${content}</div>`;
  hydrateIcons(root);
  const firstInput = root.querySelector('input, textarea, select');
  if (firstInput) window.setTimeout(() => firstInput.focus(), 40);
}

function closeModal() {
  const root = document.getElementById('modal-root');
  if (root) root.innerHTML = '';
}

function showNewProjectModal() {
  openModal(`
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="new-project-title">
      <div class="modal-header">
        <div><h2 id="new-project-title">Créer un mémoire</h2><p>Commencez par les informations essentielles. Vous pourrez les modifier plus tard.</p></div>
        <button class="modal-close" type="button" data-action="close-modal" aria-label="Fermer">${icon('x')}</button>
      </div>
      <form id="new-project-form">
        <div class="modal-body">
          <div class="form-grid">
            <label class="form-field form-field--full"><span class="form-label">Titre du mémoire</span><input class="input" type="text" name="title" placeholder="Ex. : L’impact du numérique sur…" required autofocus /></label>
            <label class="form-field"><span class="form-label">Discipline / filière</span><input class="input" type="text" name="field" placeholder="Ex. : Sciences sociales" /></label>
            <label class="form-field"><span class="form-label">Niveau</span><select class="select" name="level"><option>Licence 1</option><option>Licence 2</option><option>Licence 3</option><option>Master 1</option><option>Master 2</option><option>Doctorat</option><option>Autre</option></select></label>
            <label class="form-field"><span class="form-label">Objectif de longueur</span><input class="input" type="number" name="targetWords" min="0" step="500" value="10000" /></label>
            <label class="form-field"><span class="form-label">Échéance</span><input class="input" type="date" name="deadline" value="${addDaysToIso(60)}" /></label>
          </div>
          <div class="notice" style="margin-top: 17px;">${icon('info')} <span>Un plan en six parties sera créé automatiquement. Vous pourrez l’adapter à votre méthode.</span></div>
        </div>
        <div class="modal-footer"><span class="modal-note">Vos données restent sur cet appareil.</span><button class="button button--secondary" type="button" data-action="close-modal">Annuler</button><button class="button button--primary" type="submit">${icon('plus')} Créer le mémoire</button></div>
      </form>
    </div>
  `);
}

function showAddSectionModal() {
  openModal(`
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="new-section-title">
      <div class="modal-header">
        <div><h2 id="new-section-title">Ajouter une partie</h2><p>Découpez votre réflexion en étapes faciles à suivre.</p></div>
        <button class="modal-close" type="button" data-action="close-modal" aria-label="Fermer">${icon('x')}</button>
      </div>
      <form id="new-section-form">
        <div class="modal-body">
          <div class="form-grid">
            <label class="form-field form-field--full"><span class="form-label">Titre de la partie</span><input class="input" type="text" name="title" placeholder="Ex. : Analyse des résultats" required /></label>
            <label class="form-field form-field--full"><span class="form-label">Type de partie</span><select class="select" name="type">${Object.entries(SECTION_TYPES).map(([key, value]) => `<option value="${key}">${escapeHtml(value.label)}</option>`).join('')}</select></label>
          </div>
        </div>
        <div class="modal-footer"><button class="button button--secondary" type="button" data-action="close-modal">Annuler</button><button class="button button--primary" type="submit">${icon('plus')} Ajouter la partie</button></div>
      </form>
    </div>
  `);
}

function showCitationModal(citationId = null) {
  const project = getProject();
  if (!project) {
    showToast('Créez d’abord un mémoire.', 'error');
    return;
  }
  const citation = citationId ? project.citations.find((item) => item.id === citationId) : null;
  openModal(`
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="citation-modal-title">
      <div class="modal-header">
        <div><h2 id="citation-modal-title">${citation ? 'Modifier la référence' : 'Ajouter une référence'}</h2><p>Renseignez les informations que vous retrouverez dans votre bibliographie.</p></div>
        <button class="modal-close" type="button" data-action="close-modal" aria-label="Fermer">${icon('x')}</button>
      </div>
      <form id="citation-form">
        <input type="hidden" name="citationId" value="${citation?.id || ''}" />
        <div class="modal-body">
          <div class="form-grid">
            <label class="form-field"><span class="form-label">Auteur(s)</span><input class="input" type="text" name="author" value="${escapeHtml(citation?.author || '')}" placeholder="Ex. : Dupont, A." required /></label>
            <label class="form-field"><span class="form-label">Année</span><input class="input" type="text" name="year" value="${escapeHtml(citation?.year || new Date().getFullYear())}" placeholder="2024" required /></label>
            <label class="form-field form-field--full"><span class="form-label">Titre de la source</span><input class="input" type="text" name="title" value="${escapeHtml(citation?.title || '')}" placeholder="Titre de l’article, du livre ou du rapport" required /></label>
            <label class="form-field"><span class="form-label">Type de source</span><select class="select" name="source"><option ${citation?.source === 'Article scientifique' ? 'selected' : ''}>Article scientifique</option><option ${citation?.source === 'Livre' ? 'selected' : ''}>Livre</option><option ${citation?.source === 'Rapport' ? 'selected' : ''}>Rapport</option><option ${citation?.source === 'Thèse' ? 'selected' : ''}>Thèse</option><option ${citation?.source === 'Site web' ? 'selected' : ''}>Site web</option><option ${citation?.source === 'Autre' ? 'selected' : ''}>Autre</option></select></label>
            <label class="form-field"><span class="form-label">URL (facultatif)</span><input class="input" type="url" name="url" value="${escapeHtml(citation?.url || '')}" placeholder="https://…" /></label>
          </div>
          <div class="notice" style="margin-top: 17px;">${icon('info')} <span>Vérifiez toujours la norme de citation demandée par votre université avant la version finale.</span></div>
        </div>
        <div class="modal-footer"><button class="button button--secondary" type="button" data-action="close-modal">Annuler</button><button class="button button--primary" type="submit">${icon('save')} ${citation ? 'Enregistrer' : 'Ajouter la source'}</button></div>
      </form>
    </div>
  `);
}

function showPreviewModal() {
  const project = getProject();
  if (!project) return;
  const sections = project.sections.filter((section) => section.content.trim());
  const previewBody = sections.length
    ? sections.map((section) => `<h2>${escapeHtml(section.title)}</h2>${formatContentForPreview(section.content)}`).join('')
    : '<div class="preview-empty">Ajoutez du contenu à vos parties pour voir l’aperçu.</div>';
  openModal(`
    <div class="modal preview-modal" role="dialog" aria-modal="true" aria-labelledby="preview-title">
      <div class="modal-header">
        <div><h2 id="preview-title">Aperçu du mémoire</h2><p>Vérifiez la structure et exportez ensuite votre document.</p></div>
        <div style="display:flex; gap:7px; align-items:center;"><button class="button button--secondary button--small" type="button" data-action="print-project">${icon('external-link')} Imprimer / PDF</button><button class="modal-close" type="button" data-action="close-modal" aria-label="Fermer">${icon('x')}</button></div>
      </div>
      <div class="preview-paper"><h1>${escapeHtml(project.title)}</h1><p class="preview-subtitle">${escapeHtml(project.field || 'Mémoire académique')}${project.level ? ` · ${escapeHtml(project.level)}` : ''}</p>${previewBody}</div>
      <div class="modal-footer"><span class="modal-note">L’aperçu ne remplace pas la mise en page officielle de votre université.</span><button class="button button--secondary" type="button" data-action="close-modal">Fermer</button><button class="button button--primary" type="button" data-action="export-word">${icon('download')} Télécharger le document Word</button></div>
    </div>
  `, 'preview-backdrop');
}

function showHelpModal() {
  openModal(`
    <div class="modal modal--wide" role="dialog" aria-modal="true" aria-labelledby="help-title">
      <div class="modal-header">
        <div><h2 id="help-title">Guide de rédaction</h2><p>Les quelques réflexes qui transforment une page blanche en brouillon structuré.</p></div>
        <button class="modal-close" type="button" data-action="close-modal" aria-label="Fermer">${icon('x')}</button>
      </div>
      <div class="modal-body">
        <ol class="help-list">
          <li><span class="help-step">1</span><span><strong>Cadrez votre sujet.</strong> Écrivez en une phrase la question à laquelle votre mémoire répond. Décidez ensuite qui est votre lecteur et dans quel contexte il lit.</span></li>
          <li><span class="help-step">2</span><span><strong>Construisez un plan structuré.</strong> Une partie = une idée directrice. Dans chaque partie, announcez ce que vous allez démontrer avant de développer votre argument.</span></li>
          <li><span class="help-step">3</span><span><strong>Relisez en parallèle.</strong> Notez immédiatement l’auteur, l’année, la page et l’idée à réutiliser. Une bibliographie vivante évite les oublis.</span></li>
          <li><span class="help-step">4</span><span><strong>Gardez une trace du lien.</strong> Dans votre discussion, comparez vos résultats aux travaux précédents : c’est là que se construit votre contribution.</span></li>
          <li><span class="help-step">5</span><span><strong>Relisez à voix haute.</strong> Une phrase longue ou une idée confuse se remarque immédiatement lorsqu’elle est lue. Faites relire les passages importants.</span></li>
        </ol>
        <div class="notice" style="margin-top: 16px;">${icon('info')} <span>Le bouton « Générer un brouillon » crée un modèle de structure à personnaliser. Vérifiez toujours les informations, les sources et les règles de votre établissement.</span></div>
      </div>
      <div class="modal-footer"><button class="button button--primary" type="button" data-action="close-modal">C’est parti ${icon('arrow-right')}</button></div>
    </div>
  `);
}

function formatContentForPreview(content) {
  if (!content || !content.trim()) return '';
  return content
    .trim()
    .split(/\n{2,}/)
    .map((paragraph) => `<p>${escapeHtml(paragraph).replace(/\n/g, '<br />')}</p>`)
    .join('');
}

function generateSectionDraft(project, section) {
  const title = project.title || 'votre sujet';
  const field = project.field || 'votre discipline';
  const topic = title.toLowerCase();
  const drafts = {
    introduction: `Contexte et justification\n\nLe sujet « ${title} » s’inscrit dans une réflexion actuelle portée par les transformations de la ${field}. Il mérite d’être étudié parce qu’il touche à la fois à la théorie, aux pratiques et aux représentations.\n\nProblématique\n\nÀ partir de ce constat, nous chercherons à répondre à la question suivante : comment ${topic} peut-il être défini, observé et expliqué ? Cette question sera précisée en fonction de votre terrain et de votre méthode.\n\nObjectif et annonce du plan\n\nCe mémoire vise à proposer une analyse argumentée et à faire le lien entre les concepts, les données et les interprétations. Le premier chapitre présente le cadre théorique, le deuxième explique la méthodologie, avant de présenter les résultats, leur discussion et la conclusion.`,
    problematique: `Problématique de recherche\n\nNotre travail part d’un constat : ${title} doit être étudié au-delà d’une description pour être compris dans son contexte. La question centrale est donc la suivante : dans quelle mesure ce phénomène peut-il être expliqué à partir des approches de la ${field} ?\n\nQuestions secondaires\n\n• Quels concepts et quels auteurs permettent de délimiter le problème ?\n• Quels éléments empiriques ou documents rendent cette question pertinente ?\n• Quelles limites ou perspectives la recherche permet-elle d’ouvrir ?\n\nHypothèses de travail\n\nCes questions seront guidées par l’hypothèse que la compréhension du phénomène suppose de mettre en relation le contexte, les représentations et les pratiques observées.`,
    'cadre-theorique': `Cadre conceptuel\n\nPour construire notre analyse, nous mobiliseons les notions liées à « ${title} ». Chaque concept devra être défini précisément, puis relié aux questions de notre problématique.\n\nRevue des travaux\n\nLes travaux retenus seront présentés selon une logique de synthèse. Nous comparerons leurs objets, leurs méthodes et leurs résultats afin de faire apparaître les convergences, les désaccords et les limites.\n\nPositionnement\n\nNotre travail se distingue par son approche de [préciser l’angle original]. Cette synthèse constitue la base à partir de laquelle nous interpréterons les résultats de l’étude.`,
    methodologie: `Choix de la démarche\n\nPour répondre à la problématique, nous avons choisi une démarche [qualitative / quantitative / mixte]. Le choix est justifié par la nature des données et par la précision attendue.\n\nDonnées et procédure\n\nLa population, le lieu, la période et les outils de collecte seront précisés dans cette partie. Il faudra également expliquer le déroulement des étapes, les critères d’analyse et les mesures destinées à protéger les participants.\n\nLimites méthodologiques\n\nToute étude comporte des limites : taille de l’échantillon, accès au terrain, biais de sélection ou contraintes de temps. Leur explicitation renforce la crédibilité de l’analyse.`,
    resultats: `Présentation des résultats\n\nLes données recueillies sont présentées ci-dessous selon [préciser les thèmes ou les catégories]. Cette organisation permet de répondre à la problématique tout en conservant la trace du raisonnement analytique.\n\nAnalyse des tendances\n\nLe premier constat montre que [résultat 1]. Le second résultat est associé à [résultat 2]. Il convient de décrire ces observations avant de proposer une interprétation dans la discussion.\n\nSynthèse\n\nLes résultats confirment, nuancent ou remettent en question certains éléments du cadre théorique. Les tableaux, figures et exemples seront placés à proximité des passages qui les commentent.`,
    discussion: `Interprétation des résultats\n\nLes observations peuvent être mises en dialogue avec les travaux présentés dans la revue de la littérature. Cette comparaison permet de comprendre à la fois les convergences et les écarts avec les travaux antérieurs.\n\nRetour sur la problématique\n\nNotre analyse permet-elle de répondre à la question posée ? Les éléments recueillis éclairent le phénomène, mais certaines interprétations doivent rester prudentes.\n\nLimites et perspectives\n\nIl convient de discuter les limites de l’étude et de proposer des prolongements : outil amélioré, une nouvelle enquête, étude longitudinale ou analyse d’un terrain comparable.`,
    conclusion: `Réponse à la problématique\n\nAu terme de ce travail, nous pouvons revenir à la question initiale : [réponse synthétique à la problématique]. Cette réponse doit être nuancée et reliée aux éléments effectivement démontrés.\n\nApports du mémoire\n\nCette recherche a permis de préciser certains concepts, de documenter des pratiques et de formuler des recommandations. Les apports et les limites doivent être présentés de façon équilibrée.\n\nPerspectives\n\nPlusieurs pistes peuvent prolonger cette réflexion : approfondir le terrain, comparer d’autres périodes ou réaliser une étude longitudinale. La conclusion ouvre ainsi de nouvelles questions de recherche.`,
    annexes: `Annexe 1 — Notice\n\nPrésentez ici le document, sa source et la manière dont il a été utilisé dans le mémoire.\n\nAnnexe 2 — Documents complémentaires\n\nAjoutez ici les questionnaires, grilles d’entretien, tableaux ou illustrations utiles à la compréhension de la démarche.`,
    autre: `Objectif de la partie\n\nCette partie analyse un aspect de « ${title} » en lien avec la problématique. L’objectif est de montrer comment les éléments observés éclairent la question de recherche.\n\nDéveloppement\n\nPrésentez les arguments dans un ordre progressif. Chaque sous-partie doit répondre à une question précise et s’appuyer sur une donnée, une citation ou un raisonnement clairement identifié.\n\nTransition\n\nCette analyse prépare la prochaine partie, qui permettra de [annoncer la prochaine étape de l’argumentation].`,
  };
  return drafts[section.type] || drafts.autre;
}

function insertTextIntoEditor(text, options = {}) {
  const editor = document.getElementById('section-editor');
  if (!editor) return;
  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  const selected = editor.value.slice(start, end);
  let insertion = text;
  if (options.placeholder && !selected) insertion = options.placeholder;
  editor.setRangeText(insertion, start, end, 'end');
  editor.focus();
  editor.dispatchEvent(new Event('input', { bubbles: true }));
}

function applyTextFormat(format) {
  const editor = document.getElementById('section-editor');
  if (!editor) return;
  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  const selected = editor.value.slice(start, end);
  let replacement = '';
  let selectionStart = 0;
  let selectionEnd = 0;

  if (format === 'bold') {
    replacement = `**${selected || 'texte important'}**`;
    selectionStart = start + 2;
    selectionEnd = start + 2 + (selected || 'texte important').length;
  } else if (format === 'italic') {
    replacement = `*${selected || 'texte en italique'}*`;
    selectionStart = start + 1;
    selectionEnd = start + 1 + (selected || 'texte en italique').length;
  } else if (format === 'heading') {
    replacement = `## ${selected || 'Titre de la partie'}`;
    selectionStart = start + 3;
    selectionEnd = replacement.length;
  } else if (format === 'list') {
    const text = selected || 'Votre première idée';
    replacement = text.split('\n').map((line) => `- ${line}`).join('\n');
    selectionStart = start;
    selectionEnd = start + replacement.length;
  } else if (format === 'ordered-list') {
    const text = selected || 'Votre première idée';
    replacement = text.split('\n').map((line, index) => `${index + 1}. ${line}`).join('\n');
    selectionStart = start;
    selectionEnd = start + replacement.length;
  } else if (format === 'quote') {
    replacement = `> ${selected || 'Une citation à vérifier'}`;
    selectionStart = start + 2;
    selectionEnd = replacement.length;
  }

  editor.setRangeText(replacement, start, end, 'end');
  editor.focus();
  editor.setSelectionRange(selectionStart, selectionEnd);
  editor.dispatchEvent(new Event('input', { bubbles: true }));
}

function insertCitation(citation) {
  const reference = `(${citation.author}, ${citation.year})`;
  const editor = document.getElementById('section-editor');
  if (!editor) {
    state.view = 'editor';
    render();
    window.setTimeout(() => insertCitation(citation), 0);
    return;
  }
  insertTextIntoEditor(reference, { placeholder: reference });
  showToast(`Référence « ${citation.author}, ${citation.year} » insérée.`);
}

function slugify(value) {
  return String(value || 'memoire')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase() || 'memoire';
}

function buildWordHtml(project) {
  const sections = project.sections
    .map((section) => {
      const body = formatContentForPreview(section.content);
      return body ? `<h2>${escapeHtml(section.title)}</h2>${body}` : '';
    })
    .join('');
  return `<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>${escapeHtml(project.title)}</title><style>body{font-family:Georgia,'Times New Roman',serif;color:#222;line-height:1.7;margin:45px}h1{text-align:center;font-size:25px}h2{font-size:19px;margin-top:28px}p{white-space:pre-wrap;text-align:justify}.meta{text-align:center;color:#666;font-size:12px}</style></head><body><h1>${escapeHtml(project.title)}</h1><p class="meta">${escapeHtml(project.field || '')}${project.level ? ` · ${escapeHtml(project.level)}` : ''}</p>${sections || '<p>Les sections seront ajoutées au fur et à mesure de la rédaction.</p>'}</body></html>`;
}

function exportWord() {
  const project = getProject();
  if (!project) return;
  const blob = new Blob([buildWordHtml(project)], { type: 'application/msword;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${slugify(project.title)}.doc`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  showToast('Document Word généré. Vérifiez sa mise en page avant impression.');
}

function printProject() {
  const project = getProject();
  if (!project) return;
  const printWindow = window.open('', '_blank', 'noopener,noreferrer');
  if (!printWindow) {
    showToast('Autorisez les fenêtres pop-up pour imprimer le mémoire.', 'error');
    return;
  }
  printWindow.document.write(`<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>${escapeHtml(project.title)}</title><style>body{font-family:Georgia,'Times New Roman',serif;color:#222;line-height:1.7;margin:42px}h1{text-align:center;font-size:25px}h2{font-size:19px;margin-top:28px;page-break-after:avoid}p{white-space:pre-wrap;text-align:justify}.meta{text-align:center;color:#666;font-size:12px}</style></head><body><h1>${escapeHtml(project.title)}</h1><p class="meta">${escapeHtml(project.field || '')}${project.level ? ` · ${escapeHtml(project.level)}` : ''}</p>${buildWordHtml(project).replace(/^[\s\S]*?<body>/, '').replace(/<\/body>[\s\S]*$/, '')}</body></html>`);
  printWindow.document.close();
  printWindow.focus();
  window.setTimeout(() => {
    printWindow.print();
  }, 350);
}

function exportBackup() {
  const payload = {
    exportedAt: new Date().toISOString(),
    app: 'ThesisFlow',
    state,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `thesisflow-sauvegarde-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  showToast('Sauvegarde exportée.');
}

function updateEditorLiveStats() {
  const project = getProject();
  const section = getSection(project);
  if (!project || !section) return;
  const words = wordCount(section.content);
  const wordElement = document.getElementById('editor-word-count');
  const characterElement = document.getElementById('editor-character-count');
  if (wordElement) wordElement.textContent = formatNumber(words);
  if (characterElement) characterElement.textContent = formatNumber(section.content.length);
  const saveStatus = document.getElementById('save-status');
  if (saveStatus) saveStatus.textContent = 'Enregistrement…';
  const progressValue = document.getElementById('outline-progress-value');
  const progressBar = document.getElementById('outline-progress-bar');
  if (progressValue && progressBar) {
    const progress = getProjectProgress(project);
    progressValue.textContent = `${progress}%`;
    progressBar.style.width = `${progress}%`;
  }
}

function scheduleSave() {
  if (saveTimer) window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => {
    persist();
    const status = document.getElementById('save-status');
    if (status) status.textContent = `Enregistré à ${formatDateTime(Date.now())}`;
    saveTimer = null;
  }, 450);
}

function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type === 'error' ? 'toast--error' : 'toast--success'}`;
  toast.innerHTML = `<span class="toast-icon">${icon(type === 'error' ? 'alert-circle' : 'check')}</span><span class="toast-copy">${escapeHtml(message)}</span>`;
  container.appendChild(toast);
  window.setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(5px)';
    toast.style.transition = 'opacity 180ms ease, transform 180ms ease';
    window.setTimeout(() => toast.remove(), 190);
  }, 3400);
}

function toggleTask(taskId) {
  const section = getSection();
  if (!section) return;
  const task = section.tasks.find((item) => item.id === taskId);
  if (!task) return;
  task.done = !task.done;
  section.updatedAt = Date.now();
  getProject().updatedAt = Date.now();
  persist();
  render();
}

function toggleChecklistItem(itemId) {
  const project = getProject();
  if (!project) return;
  const item = project.checklist.find((check) => check.id === itemId);
  if (!item) return;
  item.done = !item.done;
  project.updatedAt = Date.now();
  persist();
  render();
}

function handleNavigate(view) {
  if (view === 'editor' && !getProject()) {
    showToast('Créez un mémoire pour commencer.', 'error');
    return;
  }
  state.view = view;
  if (view === 'editor' && getProject() && !getSection()) {
    state.currentSectionId = getProject().sections[0]?.id || null;
  }
  persist();
  render();
  window.scrollTo(0, 0);
  document.getElementById('main-content')?.focus({ preventScroll: true });
}

function openProject(projectId) {
  const project = state.projects.find((item) => item.id === projectId);
  if (!project) return;
  state.activeProjectId = project.id;
  state.currentSectionId = project.sections[0]?.id || null;
  state.view = 'editor';
  persist();
  render();
  window.scrollTo(0, 0);
}

function generateDraft() {
  const project = getProject();
  const section = getSection(project);
  if (!project || !section) return;
  const draft = generateSectionDraft(project, section);
  section.content = section.content.trim() ? `${section.content.trim()}\n\n---\n\n${draft}` : draft;
  section.updatedAt = Date.now();
  project.updatedAt = Date.now();
  persist();
  render();
  showToast('Un brouillon structuré a été ajouté. Personnalisez-le avec vos données.');
}

function deleteSection() {
  const project = getProject();
  const section = getSection(project);
  if (!project || !section) return;
  if (project.sections.length <= 1) {
    showToast('Un mémoire doit contenir au moins une partie.', 'error');
    return;
  }
  if (!window.confirm(`Supprimer la partie « ${section.title} » ?`)) return;
  const index = project.sections.findIndex((item) => item.id === section.id);
  project.sections.splice(index, 1);
  state.currentSectionId = project.sections[Math.max(0, index - 1)]?.id || project.sections[0].id;
  project.updatedAt = Date.now();
  persist();
  render();
  showToast('La partie a été supprimée.');
}

function duplicateSection() {
  const project = getProject();
  const section = getSection(project);
  if (!project || !section) return;
  const copy = {
    ...section,
    id: createId('section'),
    title: `${section.title} (copie)`,
    content: section.content,
    completed: false,
    updatedAt: Date.now(),
    tasks: section.tasks.map((task) => ({ ...task, id: createId('task'), done: false })),
  };
  const index = project.sections.findIndex((item) => item.id === section.id);
  project.sections.splice(index + 1, 0, copy);
  state.currentSectionId = copy.id;
  project.updatedAt = Date.now();
  persist();
  render();
  showToast('La partie a été dupliquée.');
}

function createProjectFromForm(form) {
  const formData = new FormData(form);
  const title = String(formData.get('title') || '').trim();
  if (!title) return;
  const project = {
    id: createId('project'),
    title,
    field: String(formData.get('field') || '').trim(),
    level: String(formData.get('level') || '').trim(),
    targetWords: Number(formData.get('targetWords')) || 10000,
    deadline: String(formData.get('deadline') || ''),
    createdAt: Date.now(),
    updatedAt: Date.now(),
    isDemo: false,
    sections: createDefaultSections(),
    citations: [],
    checklist: createDefaultChecklist(),
  };
  state.projects.unshift(project);
  state.activeProjectId = project.id;
  state.currentSectionId = project.sections[0].id;
  state.view = 'editor';
  persist();
  closeModal();
  render();
  showToast('Votre mémoire a été créé. Bonne rédaction !');
}

function addSectionFromForm(form) {
  const formData = new FormData(form);
  const title = String(formData.get('title') || '').trim();
  if (!title) return;
  const type = String(formData.get('type') || 'autre');
  const section = createSection(title, SECTION_TYPES[type] ? type : 'autre');
  const project = getProject();
  if (!project) return;
  project.sections.push(section);
  state.currentSectionId = section.id;
  project.updatedAt = Date.now();
  persist();
  closeModal();
  render();
  showToast('La nouvelle partie a été ajoutée au plan.');
}

function saveCitationFromForm(form) {
  const project = getProject();
  if (!project) return;
  const formData = new FormData(form);
  const citationId = String(formData.get('citationId') || '');
  const citation = {
    id: citationId || createId('citation'),
    author: String(formData.get('author') || '').trim(),
    year: String(formData.get('year') || '').trim(),
    title: String(formData.get('title') || '').trim(),
    source: String(formData.get('source') || 'Autre'),
    url: String(formData.get('url') || '').trim(),
    createdAt: Date.now(),
  };
  if (!citation.author || !citation.year || !citation.title) return;
  const existingIndex = project.citations.findIndex((item) => item.id === citationId);
  if (existingIndex >= 0) project.citations.splice(existingIndex, 1, citation);
  else project.citations.push(citation);
  project.updatedAt = Date.now();
  persist();
  closeModal();
  render();
  showToast(existingIndex >= 0 ? 'La référence a été mise à jour.' : 'La référence a été ajoutée.');
}

function deleteCitation(citationId) {
  const project = getProject();
  if (!project) return;
  const citation = project.citations.find((item) => item.id === citationId);
  if (!citation) return;
  if (!window.confirm(`Supprimer la référence « ${citation.title} » ?`)) return;
  project.citations = project.citations.filter((item) => item.id !== citationId);
  project.updatedAt = Date.now();
  persist();
  render();
  showToast('La référence a été supprimée.');
}

function resetData() {
  if (!window.confirm('Réinitialiser ThesisFlow ? Tous les mémoires locaux seront remplacés par l’exemple de démonstration.')) return;
  state = getInitialState();
  persist();
  render();
  showToast('L’espace a été réinitialisé.');
}

function handleClick(event) {
  if (event.target.classList.contains('modal-backdrop')) {
    closeModal();
    return;
  }
  const viewButton = event.target.closest('[data-view]');
  if (viewButton) {
    event.preventDefault();
    handleNavigate(viewButton.dataset.view);
    return;
  }
  const actionButton = event.target.closest('[data-action]');
  if (!actionButton) return;
  event.preventDefault();
  const action = actionButton.dataset.action;
  switch (action) {
    case 'new-project':
      showNewProjectModal();
      break;
    case 'open-project':
      openProject(actionButton.dataset.projectId);
      break;
    case 'select-section':
      state.currentSectionId = actionButton.dataset.sectionId;
      persist();
      render();
      break;
    case 'add-section':
      showAddSectionModal();
      break;
    case 'toggle-section-done': {
      const section = getSection();
      if (section) {
        section.completed = !section.completed;
        section.updatedAt = Date.now();
        getProject().updatedAt = Date.now();
        persist();
        render();
        showToast(section.completed ? 'Partie marquée comme terminée.' : 'Partie remise en cours.');
      }
      break;
    }
    case 'delete-section':
      deleteSection();
      break;
    case 'duplicate-section':
      duplicateSection();
      break;
    case 'generate-draft':
      generateDraft();
      break;
    case 'format-text':
      applyTextFormat(actionButton.dataset.format);
      break;
    case 'insert-citation':
      showCitationModal();
      break;
    case 'add-citation':
      showCitationModal();
      break;
    case 'edit-citation':
      showCitationModal(actionButton.dataset.citationId);
      break;
    case 'insert-citation-from-list': {
      const citation = getProject()?.citations.find((item) => item.id === actionButton.dataset.citationId);
      if (citation) insertCitation(citation);
      break;
    }
    case 'delete-citation':
      deleteCitation(actionButton.dataset.citationId);
      break;
    case 'preview-project':
      showPreviewModal();
      break;
    case 'print-project':
      printProject();
      break;
    case 'export-word':
      exportWord();
      break;
    case 'close-modal':
      closeModal();
      break;
    case 'show-help':
      showHelpModal();
      break;
    case 'toggle-task':
      toggleTask(actionButton.dataset.taskId);
      break;
    case 'toggle-check':
      toggleChecklistItem(actionButton.dataset.checkId);
      break;
    case 'toggle-preference': {
      const key = actionButton.dataset.preference;
      state.preferences[key] = !state.preferences[key];
      persist();
      render();
      break;
    }
    case 'show-info':
      showToast('Cet indicateur est visible dans le pied de l’éditeur.');
      break;
    case 'export-backup':
      exportBackup();
      break;
    case 'reset-data':
      resetData();
      break;
    default:
      break;
  }
}

function handleInput(event) {
  const target = event.target;
  if (target.id === 'section-editor') {
    const section = getSection();
    if (!section) return;
    section.content = target.value;
    section.updatedAt = Date.now();
    const project = getProject();
    if (project) project.updatedAt = Date.now();
    scheduleSave();
    updateEditorLiveStats();
    return;
  }
  if (target.id === 'project-title-input') {
    const project = getProject();
    if (!project) return;
    project.title = target.value;
    project.updatedAt = Date.now();
    scheduleSave();
    return;
  }
  if (target.id === 'section-title-input') {
    const section = getSection();
    if (!section) return;
    section.title = target.value;
    section.updatedAt = Date.now();
    getProject().updatedAt = Date.now();
    const outlineTitle = document.querySelector(`[data-outline-title="${section.id}"]`);
    if (outlineTitle) outlineTitle.textContent = target.value || 'Nouvelle partie';
    scheduleSave();
  }
}

function handleChange(event) {
  const target = event.target;
  if (target.id === 'section-type-select') {
    const section = getSection();
    if (!section) return;
    section.type = SECTION_TYPES[target.value] ? target.value : 'autre';
    section.tasks = getDefaultTasks(section.type);
    section.updatedAt = Date.now();
    getProject().updatedAt = Date.now();
    persist();
    render();
  }
  if (target.id === 'project-title-input') {
    persist();
  }
  if (target.id === 'section-title-input') {
    persist();
  }
}

function handleSubmit(event) {
  const form = event.target;
  if (form.id === 'new-project-form') {
    event.preventDefault();
    createProjectFromForm(form);
  } else if (form.id === 'new-section-form') {
    event.preventDefault();
    addSectionFromForm(form);
  } else if (form.id === 'citation-form') {
    event.preventDefault();
    saveCitationFromForm(form);
  } else if (form.id === 'settings-form') {
    event.preventDefault();
    const formData = new FormData(form);
    state.user.name = String(formData.get('name') || 'Camille Martin').trim() || 'Camille Martin';
    state.preferences.dailyGoal = Number(formData.get('dailyGoal')) || 0;
    const activeProjectId = String(formData.get('activeProjectId') || state.activeProjectId);
    if (state.projects.some((project) => project.id === activeProjectId)) {
      state.activeProjectId = activeProjectId;
      const project = getProject();
      if (!project.sections.some((section) => section.id === state.currentSectionId)) {
        state.currentSectionId = project.sections[0]?.id || null;
      }
    }
    persist();
    render();
    showToast('Vos préférences ont été enregistrées.');
  }
}

function handleKeydown(event) {
  if (event.key === 'Escape' && document.getElementById('modal-root').innerHTML) closeModal();
}

function bindEvents() {
  document.addEventListener('click', handleClick);
  document.addEventListener('input', handleInput);
  document.addEventListener('change', handleChange);
  document.addEventListener('submit', handleSubmit);
  document.addEventListener('keydown', handleKeydown);
}

function init() {
  state = loadState();
  hydrateIcons();
  bindEvents();
  render();
}

init();
