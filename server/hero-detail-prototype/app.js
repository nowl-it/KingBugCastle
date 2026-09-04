const hint = document.querySelector('.hint');

const sourceMappedActions = {
  pixel: 'CardInfoPanel.OnClickToggleDotIllust',
  statistics: 'CardInfoPanel.OnClickUnitStatistics',
  skill: 'CardInfoPanel.OnClickSkillButton',
  'hero-tab': 'CardInfoPanel.OnClickTab(0)',
  'growth-tab': 'CardInfoPanel.OnClickTab(1)',
  'profile-tab': 'CardInfoPanel.OnClickTab(2)',
  'skin-tab': 'CardInfoPanel.OnClickTab(3)',
};

document.querySelectorAll('.hotspot').forEach((control) => control.addEventListener('click', () => {
  const action = Object.entries(sourceMappedActions).find(([name]) => control.classList.contains(name))?.[1];
  hint.textContent = `${action} — behavior will be ported after its client trace.`;
  hint.style.opacity = '1';
  setTimeout(() => { hint.style.opacity = ''; }, 2600);
}));
