import { Routes } from '@angular/router';

import { Landing } from './features/landing/landing';
import { Listen } from './features/listen/listen';
import { MbePreview } from './features/mbe-preview/mbe-preview';

export const routes: Routes = [
  { path: '', component: Landing, title: 'Greeo' },
  { path: 'listen', component: Listen, title: 'Greeo: listening' },
  { path: 'mbe', component: MbePreview, title: 'Greeo: Mbe' }, // design preview
  { path: '**', redirectTo: '' },
];
