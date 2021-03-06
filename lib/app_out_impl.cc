/*
 * Gr-plc - IEEE 1901 module for GNU Radio
 * Copyright (C) 2016 Roee Bar <roeeb@ece.ubc.ca>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include <gnuradio/io_signature.h>
#include <sys/time.h>
#include "app_out_impl.h"
#include "logging.h"
#include <cassert>

namespace gr {
  namespace plc {

    app_out::sptr
    app_out::make(int log_level)
    {
      return gnuradio::get_initial_sptr
        (new app_out_impl(log_level));
    }

    /*
     * The private constructor
     */
    app_out_impl::app_out_impl(int log_level)
      : gr::block("app_out",
              gr::io_signature::make(1, 1, sizeof(unsigned char)),
              gr::io_signature::make(0, 0, 0)),
        d_mac_payload_offset(0),
        d_total_bytes(0),
        d_log_level(log_level)
    {
        message_port_register_out(pmt::mp("mac out"));
        message_port_register_in(pmt::mp("mac in"));
        d_mac_payload_pmt = pmt::make_u8vector(PAYLOAD_SIZE, 0);
        INIT_GR_LOG
    }

    /*
     * Our virtual destructor.
     */
    app_out_impl::~app_out_impl()
    {
    }

    bool app_out_impl::start()
    {
        struct timeval tp;
        gettimeofday(&tp, NULL);
        d_time_begin = tp.tv_sec * 1000 + tp.tv_usec / 1000;
        return true;
    }

    bool app_out_impl::stop () {
      if (d_mac_payload_offset)
        send_payload();
      return true;
    }

    void
    app_out_impl::forecast (int noutput_items, gr_vector_int &ninput_items_required)
    {
        /* <+forecast+> e.g. ninput_items_required[0] = noutput_items */
    }

    void app_out_impl::send_payload() {
      // dict
      pmt::pmt_t dict = pmt::make_dict();
      // payload
      d_mac_payload_pmt = pmt::init_u8vector(d_mac_payload_offset, d_mac_payload);

      bool payload_sent = false;
      while (!payload_sent) {
        pmt::pmt_t msg(delete_head_blocking(pmt::intern("mac in")));
        if (pmt::is_pair(msg) && pmt::symbol_to_string(pmt::car(msg)) == std::string("MAC-READY")) {
          dict = pmt::dict_add(dict, pmt::mp("msdu"), d_mac_payload_pmt);
          message_port_pub(pmt::mp("mac out"), pmt::cons(pmt::mp("MAC-TXMSDU"), dict));
          payload_sent = true;
          PRINT_DEBUG("sent payload, size = " + std::to_string(d_mac_payload_offset));
          d_total_bytes += d_mac_payload_offset;
          d_mac_payload_offset = 0;
        }
      }

      struct timeval tp;
      gettimeofday(&tp, NULL);
      long int now = tp.tv_sec * 1000 + tp.tv_usec / 1000;
      PRINT_DEBUG("Rate:" + std::to_string((double)(d_total_bytes)/(now-d_time_begin)) + " kB/s");
    }

    int
    app_out_impl::general_work (int noutput_items,
                       gr_vector_int &ninput_items,
                       gr_vector_const_void_star &input_items,
                       gr_vector_void_star &output_items)
    {
        const unsigned char *in = (const unsigned char *) input_items[0];

        int c = 0; // consumed
        while (ninput_items[0] - c) {
          int i = std::min(ninput_items[0] - c, PAYLOAD_SIZE - d_mac_payload_offset);
          memcpy(&d_mac_payload[d_mac_payload_offset], in + c, sizeof(unsigned char) * i);
          d_mac_payload_offset += i;
          c += i;
          if (d_mac_payload_offset == PAYLOAD_SIZE) {
            send_payload();
          }
        }
        consume(0, c);
        return 0;
    }

  } /* namespace plc */
} /* namespace gr */
