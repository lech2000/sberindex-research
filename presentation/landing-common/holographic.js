(() => {
  'use strict';
  const data = window.SBER_REGION_HOLOGRAM;
  const group = document.querySelector('[data-region-shapes]');
  if (!group || !data?.features) return;
  group.classList.add('region-shapes');
  const fragment = document.createDocumentFragment();
  data.features.forEach((region, index) => {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', region.d);
    path.setAttribute('fill-rule', 'evenodd');
    path.classList.add('region-shape');
    path.style.setProperty('--i', index);
    path.style.setProperty('--pulse-period', `${7.4 + (index % 7) * 0.35}s`);
    fragment.append(path);
  });
  group.append(fragment);
})();
