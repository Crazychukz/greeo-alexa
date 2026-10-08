import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';

import { GREEO_API_BASE } from './api-config';
import { ListenerSession } from './listener-session';

/** Adds the listener's identity header to Greeo API calls, and to nothing else. */
export const identityInterceptor: HttpInterceptorFn = (request, next) => {
  if (!request.url.startsWith(inject(GREEO_API_BASE))) {
    return next(request);
  }
  const headers = inject(ListenerSession).headers();
  return next(Object.keys(headers).length ? request.clone({ setHeaders: headers }) : request);
};
