/******************************************************************************
 *
 * CAEN SpA - Front End Division
 * Via Vetraia, 11 - 55049 - Viareggio ITALY
 * +390594388398 - www.caen.it
 *
 ***************************************************************************/
/**
 * \note TERMS OF USE:
 * This program is free software; you can redistribute it and/or modify it under
 * the terms of the GNU General Public License as published by the Free Software
 * Foundation. This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. The user relies on the
 * software, documentation and results solely at his own risk.
 ******************************************************************************/

#include "FERS_MultiPlatform.h"
#include "FERSlib.h" /* FERSLIB_SUCCESS, FERSLIB_ERR_GENERIC */

/* =========================================================================
 * Internal helpers (POSIX only)
 * ========================================================================= */
#ifdef FERS_OS_POSIX
/**
 * Build a struct timespec representing (now + ms milliseconds) from the
 * CLOCK_REALTIME clock. Used by f_sem_wait().
 */
static struct timespec _timespec_from_now_ms(uint32_t ms)
{
	struct timespec ts;
	clock_gettime(CLOCK_REALTIME, &ts);

	ts.tv_sec += (time_t)(ms / 1000u);
	ts.tv_nsec += (long)((ms % 1000u) * 1000000L);

	/* Carry nanoseconds overflow into seconds */
	ts.tv_sec += ts.tv_nsec / 1000000000L;
	ts.tv_nsec = ts.tv_nsec % 1000000000L;

	return ts;
}
#endif /* FERS_OS_POSIX */

/* =========================================================================
 * get_time()
 *   Returns wall-clock time in milliseconds since the Unix epoch.
 *   Both branches produce the same semantic result.
 * ========================================================================= */
uint64_t get_time(void)
{
#ifdef FERS_OS_WINDOWS
	struct _timeb tb;
	_ftime_s(&tb); /* _ftime_s is the secure variant (VS 2005+) */
	return (uint64_t)tb.time * 1000u + (uint64_t)tb.millitm;

#else /* FERS_OS_POSIX */
	struct timeval tv;
	gettimeofday(&tv, NULL);
	return (uint64_t)tv.tv_sec * 1000u + (uint64_t)tv.tv_usec / 1000u;
#endif
}

/* =========================================================================
 * GetFileUpdateTime()
 *   Returns the last-modification time of a file as a Unix timestamp
 *   (seconds since 1970-01-01 00:00:00 UTC) on all platforms.
 *
 *   NOTE: the original Windows implementation computed a non-standard
 *   timestamp from local-time fields; this version always returns a proper
 *   Unix timestamp so results are comparable across platforms.
 * ========================================================================= */
int GetFileUpdateTime(const char *fname, uint64_t *ftime)
{
	if (fname == NULL || ftime == NULL)
		return -1;

	*ftime = 0;

#ifdef FERS_OS_WINDOWS
	/* Convert the file path to UTF-16 for the Win32 API */
	wchar_t wpath[MAX_PATH];
	if (MultiByteToWideChar(CP_ACP, 0, fname, -1, wpath, MAX_PATH) == 0)
		return -1;

	HANDLE hFile = CreateFileW(
		wpath, GENERIC_READ, FILE_SHARE_READ,
		NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
	if (hFile == INVALID_HANDLE_VALUE)
		return -1;

	FILETIME ftWrite;
	if (!GetFileTime(hFile, NULL, NULL, &ftWrite))
	{
		CloseHandle(hFile);
		return -1;
	}
	CloseHandle(hFile);

	/*
	 * FILETIME counts 100-nanosecond intervals since 1601-01-01 00:00:00 UTC.
	 * Unix epoch starts at 1970-01-01 00:00:00 UTC.
	 * Difference: 11644473600 seconds.
	 */
	ULONGLONG ft100ns = ((ULONGLONG)ftWrite.dwHighDateTime << 32) |
						(ULONGLONG)ftWrite.dwLowDateTime;
	*ftime = (uint64_t)(ft100ns / 10000000ULL) - 11644473600ULL;

#else /* FERS_OS_POSIX */
	struct stat st;
	if (stat(fname, &st) != 0)
		return -1;
	*ftime = (uint64_t)st.st_mtime;
#endif

	return 0;
}

/* =========================================================================
 * Semaphore functions
 * ========================================================================= */

int f_sem_init(f_sem_t *s)
{
	if (s == NULL)
		return FERSLIB_ERR_GENERIC;

#ifdef FERS_OS_WINDOWS
	HANDLE h = CreateSemaphoreA(NULL, 0, LONG_MAX, NULL);
	if (h == NULL)
		return FERSLIB_ERR_GENERIC;
	*s = h;
#else
	if (sem_init(s, /*pshared=*/0, /*value=*/0) != 0)
		return FERSLIB_ERR_GENERIC;
#endif

	return FERSLIB_SUCCESS;
}

/* ------------------------------------------------------------------------- */

int f_sem_destroy(f_sem_t *s)
{
	if (s == NULL)
		return FERSLIB_ERR_GENERIC;

#ifdef FERS_OS_WINDOWS
	if (!CloseHandle(*s))
		return FERSLIB_ERR_GENERIC;
	*s = NULL;
#else
	if (sem_destroy(s) != 0)
		return FERSLIB_ERR_GENERIC;
#endif

	return FERSLIB_SUCCESS;
}

/* ------------------------------------------------------------------------- */

int f_sem_wait(f_sem_t *s, int32_t ms)
{
	if (s == NULL)
		return FERSLIB_ERR_GENERIC;

#ifdef FERS_OS_WINDOWS
	DWORD timeout_ms = (ms == FERS_WAIT_INFINITE) ? INFINITE : (DWORD)ms;
	DWORD r = WaitForSingleObjectEx(*s, timeout_ms, FALSE);
	if (r == WAIT_OBJECT_0)
		return FERSLIB_SUCCESS;
	/* WAIT_TIMEOUT or any other error */
	return FERSLIB_ERR_GENERIC;

#else /* FERS_OS_POSIX */
	int r;

	if (ms == FERS_WAIT_INFINITE)
	{
		/* Block indefinitely */
		do
		{
			r = sem_wait(s);
		} while (r != 0 && errno == EINTR); /* retry on signal interrupt */
		return (r == 0) ? FERSLIB_SUCCESS : FERSLIB_ERR_GENERIC;
	}

	if (ms == 0)
	{
		/* Non-blocking try */
		r = sem_trywait(s);
		if (r == 0)
			return FERSLIB_SUCCESS;
		if (errno == EAGAIN)
			return FERSLIB_ERR_GENERIC; /* would block */
		return FERSLIB_ERR_GENERIC;
	}

	/* Timed wait */
	const struct timespec ts = _timespec_from_now_ms((uint32_t)ms);
	do
	{
		r = sem_timedwait(s, &ts);
	} while (r != 0 && errno == EINTR);

	if (r == 0)
		return FERSLIB_SUCCESS;
	if (errno == ETIMEDOUT)
		return FERSLIB_ERR_GENERIC;
	return FERSLIB_ERR_GENERIC;
#endif
}

/* ------------------------------------------------------------------------- */

int f_sem_post(f_sem_t *s)
{
	if (s == NULL)
		return FERSLIB_ERR_GENERIC;

#ifdef FERS_OS_WINDOWS
	if (!ReleaseSemaphore(*s, 1, NULL))
		return FERSLIB_ERR_GENERIC;
#else
	if (sem_post(s) != 0)
		return FERSLIB_ERR_GENERIC;
#endif

	return FERSLIB_SUCCESS;
}