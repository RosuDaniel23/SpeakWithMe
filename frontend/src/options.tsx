import { type ReactNode } from 'react';
import { Heart, Utensils, Droplets, LifeBuoy, AlertTriangle, CheckCircle, Plus, Bandage, Soup, Cross, Speech, X } from 'lucide-react';

export const TOP_ICON_COLOR = 'bg-[#F5A623]';
export const RIGHT_ICON_COLOR = 'bg-[#5EEADB]';
export const BOTTOM_ICON_COLOR = 'bg-red-500';
export const LEFT_ICON_COLOR = 'bg-blue-600';

export const iconMap: Record<string, ReactNode> = {
  Heart: <Heart />,
  Utensils: <Utensils />,
  Droplets: <Droplets />,
  LifeBuoy: <LifeBuoy />,
  AlertTriangle: <AlertTriangle />,
  CheckCircle: <CheckCircle />,
  Plus: <Plus />,
  Bandage: <Bandage />,
  Soup: <Soup />,
  Cross: <Cross />,
  Speech: <Speech />,
  X: <X />,
};

export type DecisionTreeNode = {
  id: string;
  label: string;
  icon?: string;
  options?: DecisionTreeNode[];
  result?: string;
  question?: string;
};

const painLevels = [
  { id: 'no', label: 'No Pain', icon: 'CheckCircle', result: 'No pain reported' },
  { id: 'mild', label: 'Mild Pain', icon: 'Plus' },
  { id: 'moderate', label: 'Moderate Pain', icon: 'AlertTriangle' },
  { id: 'severe', label: 'Severe Pain', icon: 'AlertTriangle' }
];

const painPersistence = [
  { id: 'constant', label: 'Constant', result: 'Pain is constant' },
  { id: 'comes-goes', label: 'Comes & Goes', result: 'Pain comes and goes' },
  { id: 'movement', label: 'Only with movement', result: 'Pain only with movement' },
  { id: 'night', label: 'Worse at night', result: 'Pain worse at night' }
];

const painDuration = [
  { id: 'minutes', question: 'Does the pain persist?', label: 'Minutes', options: painPersistence, result: 'Pain duration: minutes' },
  { id: 'hours', question: 'Does the pain persist?', label: 'Hours', options: painPersistence, result: 'Pain duration: hours' },
  { id: 'days', question: 'Does the pain persist?', label: 'Days', options: painPersistence, result: 'Pain duration: days' },
  { id: 'weeks', question: 'Does the pain persist?', label: 'Weeks', options: painPersistence, result: 'Pain duration: weeks' }
];

const painTypes = [
  { id: 'sharp', question: 'When did it start?', label: 'Sharp', options: painDuration, result: 'Sharp pain reported' },
  { id: 'dull', question: 'When did it start?', label: 'Dull', options: painDuration, result: 'Dull pain reported' },
  { id: 'burning', question: 'When did it start?', label: 'Burning', options: painDuration, result: 'Burning pain reported' },
  { id: 'throbbing', question: 'When did it start?', label: 'Pressure', options: painDuration, result: 'Throbbing/Pressure pain reported' }
];

/** Generates the standard no/mild/moderate/severe options for a symptom node. */
function makePainLevels(): DecisionTreeNode[] {
  return [
    { id: 'no', label: 'No Pain', icon: 'CheckCircle', result: 'No pain reported' },
    { id: 'mild', label: 'Mild Pain', question: 'What type of pain?', icon: 'Plus', options: painTypes },
    { id: 'moderate', label: 'Moderate Pain', question: 'What type of pain?', icon: 'AlertTriangle', options: painTypes },
    { id: 'severe', label: 'Severe Pain', question: 'What type of pain?', icon: 'AlertTriangle', options: painTypes },
  ];
}


export const DECISION_TREE: DecisionTreeNode = {
  id: 'root',
  label: 'Main Menu',
  question: 'What do you need help with?',
  options: [
    {
      id: 'assistance',
      label: 'Assistance',
      question: 'What type of help?',
      icon: 'Bandage',
      options: [
        { id: 'emergency',label: 'EMERGENCY CALL', result: 'Call emergency support' },
        { id: 'adjust-position', label: 'Adjust Position', result: 'Adjust position' },
        { id: 'bathroom', label: 'Bathroom Assistance', result: 'Bathroom assistance' },
        { id: 'nurse', label: 'Need Nurse (non-critical)', result: 'Call nurse' }
      ]
    },
    {
      id: 'needs',
      label: 'Needs',
      question: 'What do you need?',
      icon: 'Soup',
      options: [
        { id: 'water', label: 'Water', result: 'Water request' },
        { id: 'food', label: 'Food', result: 'Food request' },
        { id: 'wheelchair', label: 'Wheelchair', result: 'Wheelchair request' },
        { id: 'more_needs', label: 'More Needs', result: 'Other needs' }
      ]
    },
    {
      id: 'pain',
      label: 'Pain',
      question: 'Where is the pain?',
      icon: 'Cross',
      options: [
        {
          id: 'head-neck',
          label: 'Head/Neck',
          question: 'What type of pain?',
          options: [
            { id: 'headache',  label: 'Headache/Migrane', question: 'How painful is it?', options: makePainLevels() },
            { id: 'ears',      label: 'Ears/Hearing',     question: 'How painful is it?', options: makePainLevels() },
            { id: 'throat',    label: 'Throat/Mouth',     question: 'How painful is it?', options: makePainLevels() },
            { id: 'vision',    label: 'Vision/Eyes',      question: 'How painful is it?', options: makePainLevels() },
          ]
        },
        {
          id: 'chest-lungs',
          label: 'Chest/Lungs',
          question: 'What type of pain?',
          options: [
            { id: 'breathing',        label: 'Breathing',        question: 'How painful is it?', options: makePainLevels() },
            { id: 'heart-chest',      label: 'Heart/Chest Pain', question: 'How painful is it?', options: makePainLevels() },
            { id: 'weakness-fatigue', label: 'Weakness/Fatigue', question: 'How painful is it?', options: makePainLevels() },
            { id: 'cough-mucus',      label: 'Cough & Mucus',    question: 'How painful is it?', options: makePainLevels() },
          ]
        },
        {
          id: 'abdomen',
          label: 'Abdomen / Stomach',
          question: 'What type of pain?',
          options: [
            { id: 'digestion',  label: 'Digestive issues',       question: 'How painful is it?', options: makePainLevels() },
            { id: 'kidneys',    label: 'Urinary / Kidneys',      question: 'How painful is it?', options: makePainLevels() },
            { id: 'pelvic',     label: 'Reproductive/\nPelvic', question: 'How painful is it?', options: makePainLevels() },
            { id: 'discomfort', label: 'Pain/Discomfort',        question: 'How painful is it?', options: makePainLevels() },
          ]
        },
        {
          id: 'movement',
          label: 'Arms/Legs',
          question: 'What type of pain?',
          options: [
            { id: 'joint-pain',  label: 'Joints',      question: 'How painful is it?', options: makePainLevels() },
            { id: 'mobility',    label: 'Mobility',    question: 'How painful is it?', options: makePainLevels() },
            { id: 'numbness',    label: 'Numbness',    question: 'How painful is it?', options: makePainLevels() },
            { id: 'inflamation', label: 'Inflamation', question: 'How painful is it?', options: makePainLevels() },
          ]
        }
      ]
    },
    {
      id: 'communication',
      label: "Communication",
      question: 'Select an option:',
      icon: 'Speech',
      options: [
        { id: 'yes', label: 'Yes', icon: 'CheckCircle', result: 'Affirmative' },
        { id: 'idk', label: "I Don't Know", icon: 'AlertTriangle', result: 'Uncertain' },
        { id: 'no', label: 'No', icon: 'X', result: 'Negative' },
        { id: 'repeat', label: 'Repeat', icon: 'Plus', result: 'Repeat request' }
      ]
    }
  ]
};
