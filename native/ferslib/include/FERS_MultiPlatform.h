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

#ifndef FERS_MULTIPLATFORM_H
#define FERS_MULTIPLATFORM_H

/* =========================================================================
 * Feature-test macros - must come before ANY system header
 *
 * _POSIX_C_SOURCE 200809L unlocks:
 *   - strdup, getaddrinfo, freeaddrinfo, struct addrinfo
 *   - clock_gettime, sem_timedwait
 *   - S_IFDIR, ACCESSPERMS and other stat bits
 *   - usleep
 * ========================================================================= */
#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif

/* =========================================================================
 * Standard headers - always included, platform-independent
 * ========================================================================= */
#include <stdint.h>
#include <stdbool.h>
#include <stdarg.h>
#include <stddef.h>
#include <string.h>
#include <ctype.h>
#include <inttypes.h>

/* =========================================================================
 * Platform detection
 *   FERS_OS_WINDOWS  - any Windows (MSVC, MinGW, Cygwin with _WIN32)
 *   FERS_OS_MACOS    - Apple macOS / Darwin
 *   FERS_OS_LINUX    - Linux
 *   FERS_OS_POSIX    - macOS or Linux (anything with pthreads / BSD sockets)
 * ========================================================================= */
#if defined(_WIN32) || defined(_WIN64)
#define FERS_OS_WINDOWS 1
#elif defined(__APPLE__) && defined(__MACH__)
#define FERS_OS_MACOS 1
#define FERS_OS_POSIX 1
#elif defined(__linux__)
#define FERS_OS_LINUX 1
#define FERS_OS_POSIX 1
#else
#error "Unsupported platform"
#endif

/* =========================================================================
 * Platform-specific system headers
 * ========================================================================= */
#ifdef FERS_OS_WINDOWS
#define _WINSOCKAPI_ /* prevent winsock.h being pulled by windows.h */
#include <WinSock2.h>
#include <WS2tcpip.h>
#include <Windows.h>
#include <process.h> /* _beginthreadex */
#include <direct.h>	 /* _mkdir */
#include <io.h>		 /* _access */
#include <time.h>
#include <sys/timeb.h>
#include <sys/stat.h>
#endif

#ifdef FERS_OS_POSIX
#include <pthread.h>
#include <semaphore.h>
#include <time.h>
#include <sys/time.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <netdb.h>
#include <unistd.h>
#include <errno.h>
#endif

#ifdef FERS_OS_LINUX
#include <endian.h>
#endif

/* =========================================================================
 * POSIX permission/stat bits - define fallbacks in case the compiler's
 * strict mode hides them despite _POSIX_C_SOURCE
 * ========================================================================= */
#ifndef ACCESSPERMS
#define ACCESSPERMS (S_IRWXU | S_IRWXG | S_IRWXO) /* 0777 */
#endif
#ifndef S_IFDIR
#define S_IFDIR 0040000
#endif

/* =========================================================================
 * Timeout constants
 *   FERS_WAIT_INFINITE - canonical name, use this in new code
 *   INFINITE           - legacy alias kept for existing source files
 * ========================================================================= */
#define FERS_WAIT_INFINITE INT32_C(-1)

#ifndef INFINITE
#ifdef FERS_OS_WINDOWS
/* Windows already defines INFINITE as DWORD 0xFFFFFFFF in winbase.h */
#else
#define INFINITE FERS_WAIT_INFINITE
#endif
#endif

/* =========================================================================
 * Socket abstraction
 * ========================================================================= */

/* Shutdown flags - identical numeric values on all platforms */
#define FERS_SHUT_SEND 1 /* SD_SEND  / SHUT_WR  */
#define FERS_SHUT_BOTH 2 /* SD_BOTH  / SHUT_RDWR */

/* Legacy aliases used throughout existing source files */
#define SHUT_SEND FERS_SHUT_SEND
#define SHUT_BOTH FERS_SHUT_BOTH

#ifdef FERS_OS_WINDOWS
typedef SOCKET f_socket_t;

// Send/receive size. Has colliding definition with MinGW for cross platform compilation
#if defined(_WIN32) && !defined(__MINGW32__)
typedef int ssize_t;
#endif

#define f_socket_errno WSAGetLastError()
#define f_socket_h_errno WSAGetLastError()
#define f_socket_invalid INVALID_SOCKET
#define f_socket_error SOCKET_ERROR
#define f_socket_close(s) closesocket(s)
#define f_socket_cleanup() WSACleanup()

#define j_strdup _strdup
#define f_access(p, m) _access((p), (m))
#else /* FERS_OS_POSIX */
typedef int f_socket_t;

#define f_socket_errno errno
#define f_socket_h_errno h_errno
#define f_socket_invalid (-1)
#define f_socket_error (-1)
#define f_socket_close(s) close(s)
#define f_socket_cleanup() /* nothing */

#define j_strdup strdup
#define f_access(p, m) access((p), (m))
#endif

/* =========================================================================
 * Thread / mutex / semaphore types
 * ========================================================================= */
#ifdef FERS_OS_WINDOWS
typedef HANDLE f_thread_t;
typedef HANDLE f_mutex_t;
typedef HANDLE f_sem_t;
#else
typedef pthread_t f_thread_t;
typedef pthread_mutex_t f_mutex_t;
typedef sem_t f_sem_t;
#endif

/* -------------------------------------------------------------------------
 * Mutex operations  (canonical names: f_mutex_*)
 * ------------------------------------------------------------------------- */
#ifdef FERS_OS_WINDOWS
#define f_mutex_init(m) (((m) = CreateMutexA(NULL, FALSE, NULL)) == NULL \
							 ? (int)GetLastError()                       \
							 : 0)
#define f_mutex_destroy(m) (CloseHandle(m) ? 0 : (int)GetLastError())
#define f_mutex_lock(m) (WaitForSingleObject((m), INFINITE) == WAIT_FAILED \
							 ? (int)GetLastError()                         \
							 : 0)
#define f_mutex_unlock(m) (ReleaseMutex(m) ? 0 : (int)GetLastError())
#define f_mutex_trylock(m) ((int)WaitForSingleObject((m), 0))
#else
#define f_mutex_init(m) pthread_mutex_init(&(m), NULL)
#define f_mutex_destroy(m) pthread_mutex_destroy(&(m))
#define f_mutex_lock(m) pthread_mutex_lock(&(m))
#define f_mutex_unlock(m) pthread_mutex_unlock(&(m))
#define f_mutex_trylock(m) pthread_mutex_trylock(&(m))
#endif

/* -------------------------------------------------------------------------
 * Legacy mutex aliases - map old names to new f_mutex_* so existing .c/.cpp
 * files compile without modification.
 * ------------------------------------------------------------------------- */
typedef f_mutex_t mutex_t; /* old type name used in headers/sources */

#define initmutex(m) f_mutex_init(m)
#define destroymutex(m) f_mutex_destroy(m)
#define lock(m) f_mutex_lock(m)
#define unlock(m) f_mutex_unlock(m)
#define trylock(m) f_mutex_trylock(m)

/* -------------------------------------------------------------------------
 * Thread operations  (canonical names: f_thread_*)
 * ------------------------------------------------------------------------- */
#ifdef FERS_OS_WINDOWS
#define f_thread_create(f, p, id)                                                                   \
	((*(id) = (HANDLE)_beginthreadex(NULL, 0,                                                       \
									 (unsigned int(__stdcall *)(void *))(f), (p), 0, NULL)) == NULL \
		 ? (int)GetLastError()                                                                      \
		 : 0)
#define f_thread_join(id) ((int)WaitForSingleObject((id), INFINITE))
#else
#define f_thread_create(f, p, id) pthread_create((id), NULL, (f), (p))
#define f_thread_join(id) pthread_join((id), NULL)
#endif

/* Legacy aliases used in existing source files */
#define thread_create(f, p, id) f_thread_create((f), (p), (id))
#define thread_join(id, r) f_thread_join(id)

/* -------------------------------------------------------------------------
 * Sleep  (canonical: f_sleep_ms)
 * ------------------------------------------------------------------------- */
#ifdef FERS_OS_WINDOWS
#define f_sleep_ms(ms) Sleep((DWORD)(ms))

#else

#include <time.h>

static inline void f_sleep_ms(int ms)
{
	struct timespec ts;
	ts.tv_sec = ms / 1000;
	ts.tv_nsec = (ms % 1000) * 1000000L;
	nanosleep(&ts, NULL);
}

/* Legacy alias */
#define Sleep(ms) f_sleep_ms(ms)

#endif
/* =========================================================================
 * C / C++ linkage guard
 * ========================================================================= */
#ifdef __cplusplus
extern "C"
{
#endif

	/* =========================================================================
	 * Time utilities
	 * ========================================================================= */

	/** Return current wall-clock time in milliseconds since the Unix epoch. */
	uint64_t get_time(void);

	/**
	 * Return the last-modification time of a file as a Unix timestamp (seconds
	 * since epoch). Sets *ftime = 0 and returns -1 on error.
	 */
	int GetFileUpdateTime(const char *fname, uint64_t *ftime);

	/* =========================================================================
	 * Semaphore utilities
	 * ========================================================================= */

	/** Initialise a semaphore to count 0. */
	int f_sem_init(f_sem_t *s);

	/** Destroy a semaphore. */
	int f_sem_destroy(f_sem_t *s);

	/**
	 * Wait on a semaphore.
	 * @param ms  Timeout in ms; pass FERS_WAIT_INFINITE (or INFINITE) to block.
	 */
	int f_sem_wait(f_sem_t *s, int32_t ms);

	/** Post (signal) a semaphore. */
	int f_sem_post(f_sem_t *s);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* FERS_MULTIPLATFORM_H */