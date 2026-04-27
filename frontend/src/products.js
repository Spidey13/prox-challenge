export const PRODUCTS = {
  trane_precedent: {
    id: 'trane_precedent',
    name: 'Trane Precedent RTU',
    tagline: 'Diagnostic Support Agent',
    capabilities: ['ReliaTel', 'Gas/Electric', 'Economizer', 'VAV'],
    scenarios: [
      {
        icon: '\u{1F534}',
        title: 'LED fault code',
        description: 'RTRM system LED blinking a diagnostic pattern',
        question:
          'The RTRM system LED is blinking twice every two seconds. What does this diagnostic mean and how do I identify the specific fault?',
      },
      {
        icon: '\u{2744}\u{FE0F}',
        title: "Compressor won't start",
        description: 'No cooling, compressor not running, no diagnostics',
        question:
          "The rooftop unit is not cooling. The compressor won't start and there are no fault diagnostics showing on the RTRM. How do I diagnose this?",
      },
      {
        icon: '\u{1F525}',
        title: 'Gas heat failure',
        description: 'Heat fail diagnostic or ignition module faults',
        question:
          "I'm getting a heat fail diagnostic on the RTRM. The ignition module LED is flashing 2 times. What does this indicate and what should I check?",
      },
      {
        icon: '\u{23F1}\u{FE0F}',
        title: 'Fan proving failure',
        description: 'Unit shuts down 40 seconds after starting',
        question:
          'The rooftop unit shuts down approximately 40 seconds after startup. The SERVICE LED is pulsing. How do I diagnose the fan proving switch?',
      },
      {
        icon: '\u{1F4A8}',
        title: 'Economizer fault',
        description: 'Economizer diagnostics or damper issues',
        question:
          "I'm getting an economizer fault. The mixed air temperature seems incorrect. How do I diagnose the economizer module?",
      },
      {
        icon: '\u{26A1}',
        title: 'Short cycling',
        description: 'Compressor trips on high or low pressure repeatedly',
        question:
          "The compressor keeps short cycling \u2014 runs 3 minutes then trips. The cool fail indicator is pulsing. What are the likely causes?",
      },
    ],
    escalation_copy: {
      title: 'Escalation Required',
      instruction:
        'This fault requires a certified HVAC technician. Do not proceed further without proper authorization and certification.',
      actions: [
        'Lock out / tag out the unit disconnect per LOTO procedure',
        'Record the LED flash code and all diagnostic readings',
        'Contact service dispatch with the job card reference number',
      ],
    },
  },
}

export const DEFAULT_PRODUCT_ID = 'trane_precedent'

export function getProduct(productId) {
  return PRODUCTS[productId] ?? {
    id: productId,
    name: productId,
    tagline: 'Diagnostic Support Agent',
    capabilities: [],
    scenarios: [],
    escalation_copy: null,
  }
}
