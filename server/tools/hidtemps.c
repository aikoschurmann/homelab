/* Prints every temperature sensor macOS exposes through IOHIDEventSystem, one
   "name<TAB>celsius" per line. Works without root on Apple silicon (where the SMC keys
   older tools read are gone). Built by app/services/hardware.py on first use. */
#include <stdio.h>
#include <CoreFoundation/CoreFoundation.h>
typedef struct __IOHIDEventSystemClient *IOHIDEventSystemClientRef;
typedef struct __IOHIDServiceClient *IOHIDServiceClientRef;
typedef struct __IOHIDEvent *IOHIDEventRef;
extern IOHIDEventSystemClientRef IOHIDEventSystemClientCreate(CFAllocatorRef);
extern int IOHIDEventSystemClientSetMatching(IOHIDEventSystemClientRef, CFDictionaryRef);
extern CFArrayRef IOHIDEventSystemClientCopyServices(IOHIDEventSystemClientRef);
extern IOHIDEventRef IOHIDServiceClientCopyEvent(IOHIDServiceClientRef, int64_t, int32_t, int64_t);
extern CFTypeRef IOHIDServiceClientCopyProperty(IOHIDServiceClientRef, CFStringRef);
extern double IOHIDEventGetFloatValue(IOHIDEventRef, int32_t);
#define kIOHIDEventTypeTemperature 15
#define FIELD(t) ((t) << 16)
int main(void) {
  int page = 0xff00, usage = 5;
  CFNumberRef p = CFNumberCreate(NULL, kCFNumberIntType, &page), u = CFNumberCreate(NULL, kCFNumberIntType, &usage);
  const void *k[] = { CFSTR("PrimaryUsagePage"), CFSTR("PrimaryUsage") }, *v[] = { p, u };
  CFDictionaryRef m = CFDictionaryCreate(NULL, k, v, 2, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
  IOHIDEventSystemClientRef c = IOHIDEventSystemClientCreate(kCFAllocatorDefault);
  IOHIDEventSystemClientSetMatching(c, m);
  CFArrayRef s = IOHIDEventSystemClientCopyServices(c);
  if (!s) return 1;
  for (CFIndex i = 0; i < CFArrayGetCount(s); i++) {
    IOHIDServiceClientRef sc = (IOHIDServiceClientRef)CFArrayGetValueAtIndex(s, i);
    CFStringRef name = IOHIDServiceClientCopyProperty(sc, CFSTR("Product"));
    IOHIDEventRef e = IOHIDServiceClientCopyEvent(sc, kIOHIDEventTypeTemperature, 0, 0);
    if (!name || !e) continue;
    char buf[128]; CFStringGetCString(name, buf, sizeof buf, kCFStringEncodingUTF8);
    printf("%s\t%.1f\n", buf, IOHIDEventGetFloatValue(e, FIELD(kIOHIDEventTypeTemperature)));
  }
  return 0;
}
