export const PRODUCTS = {
  vulcan_220: {
    id: 'vulcan_220',
    name: 'Vulcan OmniPro 220',
    tagline: 'Technical Support Agent',
    processes: ['MIG', 'FCAW', 'TIG', 'STICK'],
    voltages: ['120V', '240V'],
  },
}

export const DEFAULT_PRODUCT_ID = 'vulcan_220'

export function getProduct(productId) {
  return PRODUCTS[productId] ?? {
    id: productId,
    name: productId,
    tagline: 'Technical Support Agent',
    processes: [],
    voltages: [],
  }
}
